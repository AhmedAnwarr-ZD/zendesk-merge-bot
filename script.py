import os
import sys
import re
import requests
from datetime import datetime

# -----------------------------
# Environment variables / secrets
# -----------------------------
ZENDESK_EMAIL = os.getenv("EMAIL")
ZENDESK_TOKEN = os.getenv("API_TOKEN")
ZENDESK_SUBDOMAIN = os.getenv("SUBDOMAIN")
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")  # full like shopaleena.myshopify.com
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")

if not all([ZENDESK_EMAIL, ZENDESK_TOKEN, ZENDESK_SUBDOMAIN, SHOPIFY_DOMAIN, SHOPIFY_TOKEN]):
    sys.exit("❌ One or more required environment variables are missing")

ZENDESK_AUTH = (f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN)
SHOPIFY_HEADERS = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    "Content-Type": "application/json"
}

# -----------------------------
# Helper functions
# -----------------------------

def is_valid_order_name(name):
    return bool(re.match(r"^A\d+$", name))

def is_valid_email(email):
    return bool(re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email))

def is_valid_phone(phone):
    return bool(re.match(r"^\+\d{6,15}$", phone))

# -----------------------------
# User Story 1: Sync Zendesk note → Shopify order
# -----------------------------
def sync_zendesk_note_to_shopify(ticket_id, order_name):
    if not is_valid_order_name(order_name):
        sys.exit(f"❌ Invalid order format: {order_name}")

    # 1️⃣ Get internal notes from Zendesk
    zd_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}/comments.json"
    resp = requests.get(zd_url, auth=ZENDESK_AUTH)
    if resp.status_code != 200:
        sys.exit(f"❌ Zendesk API error: {resp.status_code} {resp.text}")

    comments = resp.json().get("comments", [])
    internal_notes = [c for c in comments if not c.get("public", True)]
    if not internal_notes:
        sys.exit("⚠ No internal notes found in Zendesk ticket")

    latest_note = internal_notes[-1]["body"].strip()
    note_with_order = f"Order: {order_name}\nAgent Note:\n{latest_note}"

    # 2️⃣ Find Shopify order
    shopify_url = f"https://{SHOPIFY_DOMAIN}/admin/api/2025-01/orders.json?name={order_name}"
    resp = requests.get(shopify_url, headers=SHOPIFY_HEADERS)
    if resp.status_code == 401:
        sys.exit("❌ Shopify API Unauthorized — check SHOPIFY_TOKEN")
    orders = resp.json().get("orders", [])
    if not orders:
        sys.exit(f"❌ No Shopify order found for {order_name}")
    order_id = orders[0]["id"]

    # 3️⃣ Update Shopify order note
    update_url = f"https://{SHOPIFY_DOMAIN}/admin/api/2025-01/orders/{order_id}.json"
    payload = {"order": {"id": order_id, "note": note_with_order}}
    resp = requests.put(update_url, headers=SHOPIFY_HEADERS, json=payload)
    if resp.status_code != 200:
        sys.exit(f"❌ Shopify update failed: {resp.status_code} {resp.text}")

    print(f"✅ Added internal note from Zendesk ticket {ticket_id} to Shopify order {order_name}")

# -----------------------------
# User Story 2: Retrieve customer orders
# -----------------------------
def retrieve_customer_orders(identifier):
    identifier = identifier.strip()
    if is_valid_email(identifier):
        query = f"email:{identifier}"
    elif is_valid_phone(identifier):
        query = f"phone:{identifier}"
    else:
        sys.exit("❌ Invalid email or phone format")

    shopify_url = f"https://{SHOPIFY_DOMAIN}/admin/api/2025-01/orders.json?limit=250&{query}"
    resp = requests.get(shopify_url, headers=SHOPIFY_HEADERS)
    if resp.status_code != 200:
        sys.exit(f"❌ Shopify API error: {resp.status_code} {resp.text}")

    orders = resp.json().get("orders", [])
    if not orders:
        print("⚠ No orders found for this customer")
        return

    # Sort oldest → newest
    orders.sort(key=lambda x: x["created_at"])

    for order in orders:
        print("-" * 40)
        print(f"Order Name: {order['name']}")
        created_date = datetime.strptime(order['created_at'], "%Y-%m-%dT%H:%M:%S%z")
        print(f"Created At: {created_date.strftime('%Y-%m-%d %H:%M:%S')}")
        status = order.get("financial_status", "unknown")
        fulfillment = order.get("fulfillment_status", "unfulfilled")
        print(f"Status: {status} | Fulfillment: {fulfillment}")
        shipping = order.get("shipping_address", {})
        address = f"{shipping.get('address1', '')}, {shipping.get('city', '')}, {shipping.get('province', '')}, {shipping.get('country', '')}"
        print(f"Shipping Address: {address}")

        for item in order.get("line_items", []):
            print(f"{item['name']} x {item['quantity']} - {item['price']} {order.get('currency', '')}")

        paid_amount = order.get("current_total_price", "0")
        owed_amount = float(order.get("total_due", 0))
        print(f"Order Paid Amount = {paid_amount} {order.get('currency', '')}")
        print(f"Order Owed Amount = {owed_amount} {order.get('currency', '')}")

# -----------------------------
# Main logic
# -----------------------------
if __name__ == "__main__":
    lines = sys.stdin.read().splitlines()
    action = lines[0].strip() if len(lines) > 0 else None
    ticket_id = lines[1].strip() if len(lines) > 1 else None
    order_name = lines[2].strip() if len(lines) > 2 else None
    customer_identifier = lines[3].strip() if len(lines) > 3 else None

    if action == "sync_note":
        if not ticket_id or not order_name:
            sys.exit("❌ ticket_id and order_name required for sync_note")
        sync_zendesk_note_to_shopify(ticket_id, order_name)
    elif action == "retrieve_orders":
        if not customer_identifier:
            sys.exit("❌ customer_identifier required for retrieve_orders")
        retrieve_customer_orders(customer_identifier)
    else:
        sys.exit("❌ Invalid action. Use sync_note or retrieve_orders")
