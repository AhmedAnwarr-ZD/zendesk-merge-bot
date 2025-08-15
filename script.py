import os
import sys
import requests
import re

# -----------------------------
# Environment Variables
# -----------------------------
ZENDESK_SUBDOMAIN = os.getenv("SUBDOMAIN")
ZENDESK_EMAIL = os.getenv("EMAIL")
ZENDESK_TOKEN = os.getenv("API_TOKEN")

SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")

# -----------------------------
# Arguments
# -----------------------------
if len(sys.argv) < 3:
    sys.exit("❌ Usage: python script.py <action> <param>\nActions: sync_note, retrieve_orders")

action = sys.argv[1]
param = sys.argv[2]

# -----------------------------
# Helper Functions
# -----------------------------
def zendesk_get_ticket_comments(ticket_id):
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}/comments.json"
    resp = requests.get(url, auth=(f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN))
    resp.raise_for_status()
    return resp.json().get("comments", [])

def shopify_get_order_by_name(order_name):
    url = f"https://{SHOPIFY_DOMAIN}/admin/api/2025-01/orders.json?name={order_name}"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    orders = resp.json().get("orders", [])
    return orders[0] if orders else None

def shopify_search_orders_by_email_or_phone(query):
    url = f"https://{SHOPIFY_DOMAIN}/admin/api/2025-01/customers/search.json?query={query}"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    customers = resp.json().get("customers", [])
    orders = []
    for customer in customers:
        customer_orders_url = f"https://{SHOPIFY_DOMAIN}/admin/api/2025-01/orders.json?customer_id={customer['id']}&status=any"
        customer_resp = requests.get(customer_orders_url, headers=headers)
        customer_resp.raise_for_status()
        orders.extend(customer_resp.json().get("orders", []))
    return orders

def format_orders(orders):
    formatted = []
    for order in sorted(orders, key=lambda o: o['created_at']):
        items = "\n".join([
            f"{item['name']} x {item['quantity']} qty - {item['price']} SAR"
            for item in order['line_items']
        ])
        formatted.append(
            f"Order name: {order['name']}\n"
            f"Created at: {order['created_at']}\n"
            f"Status: {order.get('financial_status', 'N/A')} | Delivery: {order.get('fulfillment_status', 'N/A')}\n"
            f"Shipping address: {order.get('shipping_address', {}).get('address1', 'N/A')}\n"
            f"{items}\n"
            f"Order paid amount: {order.get('current_total_price', '0.00')} SAR\n"
            f"Order owed amount: {float(order.get('total_due', 0.0))} SAR\n"
            "-----------------------------------------"
        )
    return "\n".join(formatted)

# -----------------------------
# Main Logic
# -----------------------------
if action == "sync_note":
    # param here is ticket_id
    ticket_id = param
    comments = zendesk_get_ticket_comments(ticket_id)
    internal_notes = [c for c in comments if not c.get("public", True)]
    if not internal_notes:
        sys.exit(f"⚠ No internal notes found in ticket {ticket_id}")

    latest_note = internal_notes[-1]["body"].strip()

    # Extract order name like A123456
    match = re.search(r"A\d+", latest_note)
    if not match:
        sys.exit("❌ No valid order name found in Zendesk comment")
    order_name = match.group(0)

    order = shopify_get_order_by_name(order_name)
    if not order:
        sys.exit(f"❌ No Shopify order found for {order_name}")

    # Append comment to Shopify order note
    note_with_ticket = f"Zendesk Ticket {ticket_id} comment:\n{latest_note}"
    update_url = f"https://{SHOPIFY_DOMAIN}/admin/api/2025-01/orders/{order['id']}.json"
    payload = {"order": {"id": order['id'], "note": note_with_ticket}}
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    resp = requests.put(update_url, headers=headers, json=payload)
    resp.raise_for_status()
    print(f"✅ Synced Zendesk ticket {ticket_id} comment to Shopify order {order_name}")

elif action == "retrieve_orders":
    # param can be email or phone
    query = param
    orders = shopify_search_orders_by_email_or_phone(query)
    if not orders:
        sys.exit(f"❌ No orders found for customer {query}")
    print(format_orders(orders))

else:
    sys.exit("❌ Invalid action. Use sync_note or retrieve_orders")
