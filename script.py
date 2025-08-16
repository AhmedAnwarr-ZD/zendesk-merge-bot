import os
import sys
import base64
import mimetypes
import requests

# Try to load local .env if python-dotenv is available
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    def load_dotenv(*args, **kwargs):  # type: ignore
        return False

# Load local .env if present
load_dotenv()


def _get_required_config():
    """Fetch and validate required environment variables each time.

    Returns a dict with validated configuration.
    Raises RuntimeError with a helpful message if any are missing.
    """
    email = os.getenv("EMAIL")
    api_token = os.getenv("API_TOKEN")
    subdomain = os.getenv("SUBDOMAIN")
    shopify_token = os.getenv("SHOPIFY_TOKEN")
    shopify_domain = os.getenv("SHOPIFY_DOMAIN")

    missing = [
        name for name, value in [
            ("EMAIL", email),
            ("API_TOKEN", api_token),
            ("SUBDOMAIN", subdomain),
            ("SHOPIFY_TOKEN", shopify_token),
            ("SHOPIFY_DOMAIN", shopify_domain),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    return {
        "EMAIL": email,
        "API_TOKEN": api_token,
        "SUBDOMAIN": subdomain,
        "SHOPIFY_TOKEN": shopify_token,
        "SHOPIFY_DOMAIN": shopify_domain,
    }


def _requests_verify_kwarg():
    """Return a dict with a 'verify' key for requests, using certifi when available.

    If ALLOW_INSECURE_SSL is set to a truthy value, disables verification.
    """
    allow_insecure = os.getenv("ALLOW_INSECURE_SSL", "").strip().lower() in {"1", "true", "yes"}
    if allow_insecure:
        return {"verify": False}
    try:
        import certifi  # type: ignore
        return {"verify": certifi.where()}
    except Exception:
        return {}


def _normalize_ticket_id(raw_ticket_id):
    """Extract digits from a potentially formatted ticket id like 'A266626'."""
    import re

    if raw_ticket_id is None:
        raise ValueError("ticket id cannot be None")
    text = str(raw_ticket_id)
    match = re.search(r"(\d+)", text)
    if not match:
        raise ValueError(f"Could not parse a numeric ticket id from: {raw_ticket_id}")
    return match.group(1)


def get_zendesk_ticket(ticket_id):
    cfg = _get_required_config()
    tid = _normalize_ticket_id(ticket_id)
    url = f"https://{cfg['SUBDOMAIN']}.zendesk.com/api/v2/tickets/{tid}.json"
    resp = requests.get(url, auth=(cfg["EMAIL"] + "/token", cfg["API_TOKEN"]), **_requests_verify_kwarg())
    resp.raise_for_status()
    return resp.json()["ticket"]


def get_order_id_from_ticket(ticket):
    """
    Extract Shopify order ID from Zendesk ticket subject or tags.
    Modify this logic based on your order ID pattern.
    """
    import re

    subject = ticket.get("subject", "") if isinstance(ticket, dict) else ""
    match = re.search(r"#(\d+)", subject)
    return match.group(1) if match else None


def _extract_order_candidates_from_text(text):
    """Extract candidate order_id and order_name from arbitrary text."""
    import re

    if not text:
        return {"order_id": None, "order_name": None}

    # Prefer explicit labels
    id_labeled = re.search(r"\border\s*id\b\s*[:#-]?\s*(\d{10,20})", text, re.I)
    name_labeled = re.search(r"\border\s*name\b\s*[:#-]?\s*([A-Za-z][A-Za-z0-9-#]{3,})", text, re.I)

    # Generic patterns
    numeric_name = re.search(r"#(\d{3,})", text)  # e.g., #12345
    alpha_digit = re.search(r"\b([A-Za-z][0-9]{5,})\b", text)  # e.g., A266626
    long_digits = re.search(r"\b(\d{10,20})\b", text)  # possible Shopify order id

    order_id = (id_labeled.group(1) if id_labeled else None) or (long_digits.group(1) if long_digits else None)

    order_name = None
    if name_labeled:
        order_name = name_labeled.group(1)
    elif numeric_name:
        order_name = f"#{numeric_name.group(1)}"
    elif alpha_digit:
        order_name = alpha_digit.group(1)

    return {"order_id": order_id, "order_name": order_name}


def _extract_order_candidates(ticket):
    """Extract possible order_id or order_name from subject/description, tags, and custom_fields."""
    subject = ticket.get("subject", "") if isinstance(ticket, dict) else ""
    description = ticket.get("description", "") if isinstance(ticket, dict) else ""
    text = f"{subject}\n{description}"

    result = _extract_order_candidates_from_text(text)

    # If not found, inspect tags and custom_fields
    if not result["order_id"] or not result["order_name"]:
        tags = ticket.get("tags") or []
        for tag in tags:
            found = _extract_order_candidates_from_text(str(tag))
            result["order_id"] = result["order_id"] or found["order_id"]
            result["order_name"] = result["order_name"] or found["order_name"]
            if result["order_id"] and result["order_name"]:
                break

    if (not result["order_id"]) or (not result["order_name"]):
        custom_fields = ticket.get("custom_fields") or []
        for field in custom_fields:
            value = field.get("value")
            found = _extract_order_candidates_from_text(str(value))
            result["order_id"] = result["order_id"] or found["order_id"]
            result["order_name"] = result["order_name"] or found["order_name"]
            if result["order_id"] and result["order_name"]:
                break

    return result


def _resolve_order_id_from_name(order_name):
    """Resolve a Shopify order id from an order name using the Admin GraphQL API.

    Tries with and without a leading '#'. Returns a string id if found else None.
    """
    cfg = _get_required_config()
    domain = cfg["SHOPIFY_DOMAIN"]
    headers = {
        "X-Shopify-Access-Token": cfg["SHOPIFY_TOKEN"],
        "Content-Type": "application/json",
    }
    url = f"https://{domain}.myshopify.com/admin/api/2024-01/graphql.json"

    def query_for(candidate_name):
        # Quote the name for Shopify search syntax
        q = f"name:\"{candidate_name}\""
        query = {
            "query": (
                "query($q: String!) { orders(first: 1, query: $q) { edges { node { id name } } } }"
            ),
            "variables": {"q": q},
        }
        resp = requests.post(url, headers=headers, json=query, **_requests_verify_kwarg())
        resp.raise_for_status()
        data = resp.json()
        edges = (((data or {}).get("data") or {}).get("orders") or {}).get("edges") or []
        if not edges:
            return None
        node = edges[0].get("node") or {}
        gid = node.get("id") or ""
        if gid.startswith("gid://shopify/Order/"):
            return gid.rsplit("/", 1)[-1]
        raw_id = node.get("legacyResourceId") or node.get("id")
        return str(raw_id) if raw_id else None

    candidates = [order_name]
    if order_name.startswith("#"):
        candidates.append(order_name.lstrip("#"))
    else:
        candidates.append(f"#{order_name}")

    for cand in candidates:
        try:
            resolved = query_for(cand)
            if resolved:
                return resolved
        except Exception:
            continue
    return None


def append_order_note(order_id, note_text):
    cfg = _get_required_config()
    url = (
        f"https://{cfg['SHOPIFY_DOMAIN']}.myshopify.com/admin/api/2024-01/orders/{order_id}.json"
    )
    headers = {
        "X-Shopify-Access-Token": cfg["SHOPIFY_TOKEN"],
        "Content-Type": "application/json",
    }
    payload = {"order": {"id": int(order_id), "note": note_text}}
    resp = requests.put(url, headers=headers, json=payload, **_requests_verify_kwarg())
    resp.raise_for_status()
    return resp.json()


# Optional attachment support (disabled by default)

def _should_upload_attachments():
    return os.getenv("UPLOAD_ZENDESK_ATTACHMENTS", "").strip().lower() in {"1", "true", "yes"}


def _get_ticket_comments(ticket_id):
    cfg = _get_required_config()
    tid = _normalize_ticket_id(ticket_id)
    url = f"https://{cfg['SUBDOMAIN']}.zendesk.com/api/v2/tickets/{tid}/comments.json"
    resp = requests.get(url, auth=(cfg["EMAIL"] + "/token", cfg["API_TOKEN"]), **_requests_verify_kwarg())
    resp.raise_for_status()
    return resp.json().get("comments", [])


def _download_zendesk_attachment(content_url):
    cfg = _get_required_config()
    resp = requests.get(content_url, auth=(cfg["EMAIL"] + "/token", cfg["API_TOKEN"]), **_requests_verify_kwarg())
    resp.raise_for_status()
    return resp.content


def upload_file_to_shopify_bytes(filename, file_bytes):
    cfg = _get_required_config()
    url = f"https://{cfg['SHOPIFY_DOMAIN']}.myshopify.com/admin/api/2024-01/files.json"
    headers = {
        "X-Shopify-Access-Token": cfg["SHOPIFY_TOKEN"],
        "Content-Type": "application/json",
    }
    encoded = base64.b64encode(file_bytes).decode("ascii")
    payload = {
        "file": {
            "filename": filename,
            "attachment": encoded,
        }
    }
    resp = requests.post(url, headers=headers, json=payload, **_requests_verify_kwarg())
    resp.raise_for_status()
    data = resp.json().get("file") or {}
    return data.get("public_url") or data.get("url") or ""


def _extract_from_comments_if_needed(ticket_id, current):
    if current.get("order_id") and current.get("order_name"):
        return current
    try:
        comments = _get_ticket_comments(ticket_id)
    except Exception:
        return current
    for comment in comments[::-1]:  # newest first
        text = (comment.get("body") or "") + "\n" + (comment.get("plain_body") or "")
        found = _extract_order_candidates_from_text(text)
        current["order_id"] = current.get("order_id") or found["order_id"]
        current["order_name"] = current.get("order_name") or found["order_name"]
        if current["order_id"] and current["order_name"]:
            break
    return current


def sync_note(ticket_id):
    ticket = get_zendesk_ticket(ticket_id)

    # Extract order info from subject/description for logging and resolution
    candidates = _extract_order_candidates(ticket)
    candidates = _extract_from_comments_if_needed(ticket_id, candidates)

    if candidates.get("order_id"):
        print(f"Found Shopify order id in note: {candidates['order_id']}")
    if candidates.get("order_name"):
        print(f"Found order name in note: {candidates['order_name']}")

    # Legacy subject-based extraction
    order_id = get_order_id_from_ticket(ticket)

    # Fallback to extracted id from text
    if not order_id and candidates.get("order_id"):
        order_id = candidates["order_id"]

    # If we have an order name but no id, try to resolve via Shopify API
    if not order_id and candidates.get("order_name"):
        resolved = _resolve_order_id_from_name(candidates["order_name"])
        if resolved:
            print(
                f"Resolved order name {candidates['order_name']} to Shopify order id {resolved}"
            )
            order_id = resolved
        else:
            print(
                f"Found order name {candidates['order_name']} but could not resolve to a Shopify order id"
            )

    if not order_id:
        print(f"No Shopify order ID found in ticket {_normalize_ticket_id(ticket_id)}")
        return

    comment_text = ticket.get("description", "")
    final_note_parts = [f"Zendesk Ticket #{_normalize_ticket_id(ticket_id)}: {comment_text}" ]

    # Optionally upload the first attachment from comments and include link in note
    if _should_upload_attachments():
        comments = _get_ticket_comments(ticket_id)
        for comment in comments:
            attachments = comment.get("attachments") or []
            if not attachments:
                continue
            first = attachments[0]
            filename = first.get("file_name") or "attachment"
            content_url = first.get("content_url")
            if content_url:
                content = _download_zendesk_attachment(content_url)
                file_url = upload_file_to_shopify_bytes(filename, content)
                if file_url:
                    final_note_parts.append(f"Attachment uploaded: {file_url}")
                break

    final_note = "\n".join(final_note_parts)
    append_order_note(order_id, final_note)
    print(f"Synced ticket #{_normalize_ticket_id(ticket_id)} to Shopify order #{order_id}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python script.py sync_note <ticket_id>")
        sys.exit(1)

    action = sys.argv[1]
    ticket_id = sys.argv[2]

    if action == "sync_note":
        sync_note(ticket_id)
    else:
        print(f"Action '{action}' not supported.")
