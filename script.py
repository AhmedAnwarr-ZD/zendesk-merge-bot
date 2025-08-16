import os
import sys
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
        # Caller may be in a constrained environment; explicitly disable verification
        return {"verify": False}
    try:
        import certifi  # type: ignore
        return {"verify": certifi.where()}
    except Exception:
        # Fallback to requests default behavior
        return {}


def get_zendesk_ticket(ticket_id):
    cfg = _get_required_config()
    url = f"https://{cfg['SUBDOMAIN']}.zendesk.com/api/v2/tickets/{ticket_id}.json"
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


def sync_note(ticket_id):
    ticket = get_zendesk_ticket(ticket_id)
    order_id = get_order_id_from_ticket(ticket)
    if not order_id:
        print(f"No Shopify order ID found in ticket {ticket_id}")
        return

    comment_text = ticket.get("description", "")
    final_note = f"Zendesk Ticket #{ticket_id}: {comment_text}"
    append_order_note(order_id, final_note)
    print(f"Synced ticket #{ticket_id} to Shopify order #{order_id}")


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
