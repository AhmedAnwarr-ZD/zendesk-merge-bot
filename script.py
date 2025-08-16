import os
import sys
import requests
import re
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
    resp = requests.get(url, auth=(EMAIL + "/token", API_TOKEN), verify=False)
    resp.raise_for_status()
    return resp.json()["ticket"]

def get_order_name_from_internal_notes(ticket):
    """
    Extract Shopify order name from INTERNAL notes only.
    Matches formats: A123456, a123456789 etc.
    """
    internal_notes = ticket.get("audit", {}).get("events", [])
    for note in internal_notes:
        if note.get("type") == "Comment" and note.get("public") is False:
            body = note.get("body", "")
            match = re.search(r"\b[aA]\d+\b", body)
            if match:
                return match.group(0)
    return None

def find_order_id_by_name(order_name):
    """
    Shopify API cannot GET by 'name', so fetch orders and match manually.
    """
    url = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2024-01/orders.json?status=any&limit=250"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    resp = requests.get(url, headers=headers, verify=False)  # skip SSL verification
    resp.raise_for_status()
    orders = resp.json().get("orders", [])
    
    for order in orders:
        if order.get("name", "").lower() == order_name.lower():
            return order["id"]
    return None

def append_order_note(order_name, note_text):
    order_id = find_order_id_by_name(order_name)
    if not order_id:
        print(f"No Shopify order ID found for order name {order_name}")
        return
    
    url = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2024-01/orders/{order_id}.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {"order": {"id": order_id, "note": note_text}}
    resp = requests.put(url, headers=headers, json=payload, verify=False)  # skip SSL
    resp.raise_for_status()
    return resp.json()

def sync_note(ticket_id):
    ticket = get_zendesk_ticket(ticket_id)
    
    order_name = get_order_name_from_internal_notes(ticket)
    if not order_name:
        print(f"No Shopify order name found in internal notes of ticket {ticket_id}")
        return

    comment_text = ticket.get("description", "")
    final_note = f"Zendesk Ticket #{ticket_id}: {comment_text}"
    append_order_note(order_name, final_note)
    print(f"Synced ticket #{ticket_id} to Shopify order {order_name}")

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
