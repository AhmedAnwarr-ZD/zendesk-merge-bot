import os
import sys
import re
import requests
from dotenv import load_dotenv

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

def get_order_name_from_internal_note(ticket_id):
    """
    Extract Shopify order name from the most recent internal note.
    Matches only formats: A123456 or a123456 (any number of digits).
    """
    url = f"{ZENDESK_API_URL}/tickets/{ticket_id}/comments.json"
    resp = requests.get(url, auth=(EMAIL + "/token", API_TOKEN))
    resp.raise_for_status()
    comments = resp.json()["comments"]

    for comment in reversed(comments):  # check newest first
        if not comment.get("public", True):  # internal note only
            body = comment.get("body", "")
            match = re.search(r"[Aa]\d+", body)
            if match:
                return match.group(0)
    return None

def append_order_note(order_name, note_text):
    """
    Update Shopify order note. Shopify API allows order lookup by name, but if you want
    to update by ID you'll need to fetch the order ID first.
    """
    # First, fetch order by name
    search_url = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2024-01/orders.json?name={order_name}"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    resp = requests.get(search_url, headers=headers)
    resp.raise_for_status()
    orders = resp.json().get("orders", [])

    if not orders:
        print(f"No Shopify order found with name {order_name}")
        return

    order_id = orders[0]["id"]
    update_url = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2024-01/orders/{order_id}.json"
    payload = {"order": {"id": order_id, "note": note_text}}
    resp = requests.put(update_url, headers=headers, json=payload)
    resp.raise_for_status()
    print(f"Synced internal note to Shopify order {order_name} (ID: {order_id})")

def sync_note(ticket_id):
    order_name = get_order_name_from_internal_note(ticket_id)
    if not order_name:
        print(f"No Shopify order name found in internal notes of ticket {ticket_id}")
        return

    ticket = get_zendesk_ticket(ticket_id)
    comment_text = ticket.get("description", "")
    final_note = f"Zendesk Ticket #{ticket_id}: {comment_text}"

    append_order_note(order_name, final_note)

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
