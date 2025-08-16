import os
import re
import sys
import requests

# Load secrets from environment
ZENDESK_TOKEN = os.getenv("API_TOKEN")
ZENDESK_EMAIL = os.getenv("EMAIL")
ZENDESK_SUBDOMAIN = os.getenv("SUBDOMAIN")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")

ZENDESK_API = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2"
SHOPIFY_API = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2024-01"


def get_ticket_comments(ticket_id):
    url = f"{ZENDESK_API}/tickets/{ticket_id}/comments.json"
    resp = requests.get(url, auth=(f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN))
    resp.raise_for_status()
    return resp.json()["comments"]


def extract_order_and_comment(text):
    """Extracts (A12345 comment text) pattern, case-insensitive for 'A'"""
    match = re.search(r"\(([Aa]\d+)\s+(.+?)\)", text)
    if match:
        return match.group(1), match.group(2)
    return None, None


def append_order_note(order_id, note):
    """Append a note to Shopify order timeline"""
    url = f"{SHOPIFY_API}/orders/{order_id}/notes.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    payload = {"note": note}

    resp = requests.put(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()


def sync_note(ticket_id):
    comments = get_ticket_comments(ticket_id)
    for c in reversed(comments):  # latest first
        if not c["public"]:  # internal note
            order_id, comment_text = extract_order_and_comment(c["body"])
            if order_id:
                final_note = f"From Zendesk Ticket {ticket_id}: {comment_text}"

                # Append note to Shopify order (strip 'A' or 'a')
                append_order_note(order_id[1:], final_note)
                print(f"✅ Synced note from Zendesk ticket {ticket_id} to Shopify order {order_id}")
                return
    print(f"❌ No valid order pattern like (A12345 comment) found in ticket {ticket_id}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "sync_note":
        print("Usage: python script.py sync_note <ticket_id>")
        sys.exit(1)

    ticket_id = sys.argv[2]
    sync_note(ticket_id)
