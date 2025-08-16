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
    # Guess content type; Shopify requires only attachment; filename for display
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


def sync_note(ticket_id):
    ticket = get_zendesk_ticket(ticket_id)
    order_id = get_order_id_from_ticket(ticket)
    if not order_id:
        print(f"No Shopify order ID found in ticket {ticket_id}")
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
