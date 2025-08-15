import os
import sys
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Check environment variables
required_env_vars = [
    "SHOPIFY_TOKEN",
    "SHOPIFY_DOMAIN",
    "ZENDESK_EMAIL",
    "ZENDESK_TOKEN",
    "ZENDESK_DOMAIN"
]

missing_vars = [var for var in required_env_vars if not os.getenv(var)]

if missing_vars:
    sys.exit(f"❌ Missing required environment variables: {', '.join(missing_vars)}")

import requests

def sync_order_note_from_zendesk(ticket_id):
    # Get order name from Zendesk ticket
    zendesk_url = f"https://{os.getenv('ZENDESK_DOMAIN')}.zendesk.com/api/v2/tickets/{ticket_id}.json"
    auth = (f"{os.getenv('ZENDESK_EMAIL')}/token", os.getenv("ZENDESK_API_TOKEN"))

    resp = requests.get(zendesk_url, auth=auth)
    if resp.status_code != 200:
        sys.exit(f"❌ Failed to fetch ticket from Zendesk: {resp.status_code} - {resp.text}")

    ticket_data = resp.json()
    subject = ticket_data['ticket']['subject']

    # Extract order name like A#### from subject
    import re
    match = re.search(r"\bA\d{4,}\b", subject)
    if not match:
        sys.exit(f"❌ No order name found in ticket subject: {subject}")

    order_name = match.group(0)

    # Fetch Shopify order by name
    shopify_url = f"https://{os.getenv('SHOPIFY_DOMAIN')}/admin/api/2024-07/orders.json?name={order_name}"
    headers = {"X-Shopify-Access-Token": os.getenv("SHOPIFY_TOKEN")}

    shopify_resp = requests.get(shopify_url, headers=headers)
    if shopify_resp.status_code != 200:
        sys.exit(f"❌ Failed to fetch order from Shopify: {shopify_resp.status_code} - {shopify_resp.text}")

    orders = shopify_resp.json().get("orders", [])
    if not orders:
        sys.exit(f"❌ No Shopify order found for {order_name}")

    order_id = orders[0]['id']

    # Sync note to Shopify
    note_text = f"Zendesk ticket: {ticket_id}"
    update_url = f"https://{os.getenv('SHOPIFY_DOMAIN')}/admin/api/2024-07/orders/{order_id}.json"
    update_data = {"order": {"id": order_id, "note": note_text}}

    update_resp = requests.put(update_url, headers=headers, json=update_data)
    if update_resp.status_code != 200:
        sys.exit(f"❌ Failed to update order note: {update_resp.status_code} - {update_resp.text}")

    print(f"✅ Successfully synced note to Shopify order {order_name}")

if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "sync_note":
        sys.exit("Usage: python script.py sync_note <ticket_id>")
    sync_order_note_from_zendesk(sys.argv[2])
