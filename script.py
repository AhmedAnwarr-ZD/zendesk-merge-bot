import os
import requests
import re
import sys

# ------------------------
# Environment Variables
# ------------------------
ZENDESK_SUBDOMAIN = os.getenv("SUBDOMAIN")
ZENDESK_EMAIL = os.getenv("EMAIL")
ZENDESK_TOKEN = os.getenv("API_TOKEN")
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")

if not all([ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_TOKEN, SHOPIFY_DOMAIN, SHOPIFY_TOKEN]):
    sys.exit("❌ Missing one or more required environment variables.")

# ------------------------
# Helper Functions
# ------------------------
def get_zendesk_ticket(ticket_id):
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}/comments.json"
    resp = requests.get(url, auth=(f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN))
    if resp.status_code != 200:
        sys.exit(f"❌ Failed to fetch Zendesk ticket {ticket_id}: {resp.text}")
    return resp.json().get("comments", [])

def update_shopify_order_note(order_number, note_body):
    url = f"https://{SHOPIFY_DOMAIN}/admin/api/2025-01/orders.json?name={order_number}"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        sys.exit(f"❌ Shopify order fetch failed: {resp.text}")
    orders = resp.json().get("orders", [])
    if not orders:
        sys.exit(f"❌ No Shopify order found for {order_number}")
    order_id = orders[0]["id"]

    # Update note
    payload = {"order": {"id": order_id, "note": note_body}}
    update_url = f"https://{SHOPIFY_DOMAIN}/admin/api/2025-01/orders/{order_id}.json"
    update_resp = requests.put(update_url, headers=headers, json=payload)
    if update_resp.status_code != 200:
        sys.exit(f"❌ Failed to update Shopify order {order_number}: {update_resp.text}")
    print(f"✅ Shopify order {order_number} updated with note.")

def retrieve_shopify_orders_by_customer(identifier):
    # identifier can be email or phone
    url = f"https://{SHOPIFY_DOMAIN}/admin/api/2025-01/customers/search.json?query={identifier}"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        sys.exit(f"❌ Failed to search customer {identifier}: {resp.text}")
    customers = resp.json().get("customers", [])
    if not customers:
        print(f"⚠ No customers found for {identifier}")
        return

    for customer in customers:
        customer_id = customer["id"]
        orders_url = f"https://{SHOPIFY_DOMAIN}/admin/api/2025-01/orders.json?customer_id={customer_id}&status=any&order=created_at asc"
        orders_resp = requests.get(orders_url, headers=headers)
        if orders_resp.status_code != 200:
            print(f"❌ Failed to fetch orders for customer {customer_id}")
            continue
        orders = orders_resp.json().get("orders", [])
        if not orders:
            print(f"⚠ No orders for customer {customer.get('email')}")
            continue

        for o in orders:
            print(f"Order: {o['name']}")
            print(f"Created: {o['created_at']}")
            print(f"Status | Delivery: {o['financial_status']} | {o['fulfillment_status']}")
            print(f"Shipping: {o['shipping_address']}")
            for item in o.get("line_items", []):
                print(f"{item['name']} x {item['quantity']} - {item['price']} SAR")
            print(f"Paid: {o['current_total_price']} SAR")
            print(f"Owed: {float(o['total_price']) - float(o['current_total_price'])} SAR")
            print("-"*40)

# ------------------------
# Main Logic
# ------------------------
if len(sys.argv) < 2:
    sys.exit("❌ Action required: sync_note or retrieve_orders")

action = sys.argv[1]

if action == "sync_note":
    ticket_id = sys.argv[2] if len(sys.argv) > 2 else None
    if not ticket_id:
        sys.exit("❌ Provide ticket ID for sync_note")

    comments = get_zendesk_ticket(ticket_id)
    # Take latest internal note
    internal_notes = [c for c in comments if not c.get("public", True)]
    if not internal_notes:
        sys.exit("⚠ No internal notes found")
    latest_note = internal_notes[-1]["body"]

    # Extract order number A###### from note
    match = re.search(r"(A\d{6,})", latest_note)
    if not match:
        sys.exit("⚠ No valid order number found in note")
    order_number = match.group(1)
    note_body = f"Zendesk comment: {latest_note}"
    update_shopify_order_note(order_number, note_body)

elif action == "retrieve_orders":
    identifier = sys.argv[2] if len(sys.argv) > 2 else None
    if not identifier:
        sys.exit("❌ Provide email or phone number")
    retrieve_shopify_orders_by_customer(identifier)
else:
    sys.exit("❌ Invalid action. Use sync_note or retrieve_orders")
