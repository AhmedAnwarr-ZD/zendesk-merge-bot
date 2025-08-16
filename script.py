import os
import sys
import re
import requests

# ------------------------
# Environment variables
# ------------------------
SUBDOMAIN = os.environ["SUBDOMAIN"]
EMAIL = os.environ["EMAIL"]
API_TOKEN = os.environ["API_TOKEN"]
SHOPIFY_DOMAIN = os.environ["SHOPIFY_DOMAIN"]
SHOPIFY_TOKEN = os.environ["SHOPIFY_TOKEN"]

BASE_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
AUTH = (f"{EMAIL}/token", API_TOKEN)


# ------------------------
# Zendesk Helpers
# ------------------------
def zendesk_get(url):
    resp = requests.get(url, auth=AUTH)
    if resp.status_code != 200:
        sys.exit(f"❌ Zendesk GET failed: {resp.status_code} - {resp.text}")
    return resp.json()


def get_ticket_comments(ticket_id):
    url = f"{BASE_URL}/tickets/{ticket_id}/comments.json"
    data = zendesk_get(url)
    return data.get("comments", [])


# ------------------------
# Shopify Helpers
# ------------------------
def get_shopify_order(order_name):
    url = f"https://{SHOPIFY_DOMAIN}/admin/api/2024-07/orders.json?name={order_name}"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        sys.exit(f"❌ Failed to fetch order from Shopify: {resp.status_code} - {resp.text}")
    orders = resp.json().get("orders", [])
    return orders[0] if orders else None


def update_shopify_order_note(order_id, note_text):
    url = f"https://{SHOPIFY_DOMAIN}/admin/api/2024-07/orders/{order_id}.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    data = {"order": {"id": order_id, "note": note_text}}
    resp = requests.put(url, headers=headers, json=data)
    if resp.status_code != 200:
        sys.exit(f"❌ Failed to update order note: {resp.status_code} - {resp.text}")
    return True


# ------------------------
# Main Sync Logic
# ------------------------
def sync_note(ticket_id):
    ticket = get_ticket(ticket_id)
    if not ticket:
        print(f"❌ Ticket {ticket_id} not found.")
        return

    # Look through all comments/notes
    for comment in ticket["comments"]:
        note_text = comment["body"]

        # ✅ Loosened regex: match order number A123456 regardless of what follows
        match = re.search(r"A(\d+)\b", note_text)
        if match:
            order_id = match.group(1)
            print(f"✅ Found order ID: {order_id} in note: {note_text}")

            # Example: sync logic here
            sync_order_with_ticket(order_id, ticket_id)
            return

    print(f"❌ No valid order ID found in notes for ticket {ticket_id}.")

    # Fetch order from Shopify
    order = get_shopify_order(order_name)
    if not order:
        sys.exit(f"❌ No Shopify order found for {order_name}")

    # Update note on Shopify order
    final_note = f"Zendesk ticket {ticket_id}: {note_text}".strip()
    update_shopify_order_note(order["id"], final_note)

    print(f"✅ Synced Zendesk note to Shopify order {order_name} → {final_note}")


# ------------------------
# CLI entrypoint
# ------------------------
if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "sync_note":
        sys.exit("Usage: python script.py sync_note <ticket_id>")
    sync_note_to_shopify(sys.argv[2])
