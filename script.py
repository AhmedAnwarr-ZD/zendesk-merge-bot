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
def sync_note_to_shopify(ticket_id):
    comments = get_ticket_comments(ticket_id)

    # Find the first comment containing an order number like (A12345 ...)
    order_name = None
    note_text = None
    for c in comments:
        match = re.search(r"\(A\d{4,}.*?\)", c.get("body", ""))
        if match:
            full_match = match.group(0)        # e.g. (A12345 comment)
            parts = full_match.strip("()").split(" ", 1)
            order_name = parts[0]              # A12345
            note_text = parts[1] if len(parts) > 1 else ""
            break

    if not order_name:
        sys.exit(f"❌ No valid order pattern like (A12345 comment) found in ticket {ticket_id}")

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
