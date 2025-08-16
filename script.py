import os
import sys
import requests
from dotenv import load_dotenv
import re

# Load local .env if present
load_dotenv()

# Environment variables
EMAIL = os.getenv("EMAIL")
API_TOKEN = os.getenv("API_TOKEN")
SUBDOMAIN = os.getenv("SUBDOMAIN")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")

ZENDESK_API_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"

def get_zendesk_ticket(ticket_id):
    url = f"{ZENDESK_API_URL}/tickets/{ticket_id}.json"
    resp = requests.get(url, auth=(EMAIL + "/token", API_TOKEN))
    resp.raise_for_status()
    return resp.json()["ticket"]

def get_order_id_from_internal_note(ticket_id):
    """
    Extract Shopify order ID from the latest Zendesk internal note (public=False)
    """
    url = f"{ZENDESK_API_URL}/tickets/{ticket_id}/comments.json"
    resp = requests.get(url, auth=(EMAIL + "/token", API_TOKEN))
    resp.raise_for_status()
    comments = resp.json()["comments"]

    # Look from latest to oldest
    for comment in reversed(comments):
        if not comment.get("public", True):  # internal note only
            body = comment.get("body", "")
            match = re.search(r"#(\d+)", body)  # adjust regex to your order pattern
            if match:
                return match.group(1)
    return None

def append_order_note(order_id, note_text):
    url = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2024-01/orders/{order_id}.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {"order": {"id": order_id, "note": note_text}}
    resp = requests.put(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()

def sync_note(ticket_id):
    ticket = get_zendesk_ticket(ticket_id)
    order_id = get_order_id_from_internal_note(ticket_id)
    if not order_id:
        print(f"No Shopify order ID found in internal notes of ticket {ticket_id}")
        return
    
    # Use the ticket description as comment text
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
