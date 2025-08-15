import os
import sys
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Environment variables
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")
ZENDESK_TOKEN = os.getenv("ZENDESK_TOKEN")
ZENDESK_DOMAIN = os.getenv("ZENDESK_DOMAIN")

if not all([SHOPIFY_TOKEN, SHOPIFY_DOMAIN, ZENDESK_TOKEN, ZENDESK_DOMAIN]):
    sys.exit("❌ Missing required environment variables.")

def get_ticket_details(ticket_id):
    """Fetch Zendesk ticket details."""
    url = f"https://{ZENDESK_DOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
    headers = {
        "Authorization": f"Bearer {ZENDESK_TOKEN}",
        "Content-Type": "application/json"
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json().get("ticket", {})

def get_shopify_order_by_name(order_name):
    """Fetch Shopify order details by order name (e.g., A123456)."""
    url = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2025-01/orders.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    params = {"name": order_name}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    orders = response.json().get("orders", [])
    return orders[0] if orders else None

def sync_note_to_shopify(ticket_id):
    """Sync ticket public comment to Shopify order note."""
    ticket = get_ticket_details(ticket_id)
    order_name = None

    # Example: Extract order name from ticket subject or custom field
    subject = ticket.get("subject", "")
    if subject and subject.startswith("A"):
        order_name = subject.strip()

    if not order_name:
        sys.exit(f"❌ No order name found in ticket {ticket_id}")

    order = get_shopify_order_by_name(order_name)
    if not order:
        sys.exit(f"❌ No Shopify order found for {order_name}. Please verify the order name and try again.")

    order_id = order["id"]
    comment = ticket.get("description", "").strip()

    # Update Shopify order note
    url = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2025-01/orders/{order_id}.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {"order": {"id": order_id, "note": comment}}
    response = requests.put(url, headers=headers, json=payload)
    response.raise_for_status()

    print(f"✅ Note synced to Shopify order {order_name} ({order_id})")

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "sync_note":
        sys.exit("Usage: python script.py sync_note <ticket_id>")
    ticket_id = sys.argv[2]
    sync_note_to_shopify(ticket_id)
