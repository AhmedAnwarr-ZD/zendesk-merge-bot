import os
import requests
import sys

order_number = os.getenv("ORDER_NUMBER")
ticket_id = os.getenv("TICKET_ID")
zendesk_subdomain = os.getenv("ZENDESK_SUBDOMAIN")
zendesk_email = os.getenv("ZENDESK_EMAIL")
zendesk_token = os.getenv("ZENDESK_TOKEN")
shopify_domain = os.getenv("SHOPIFY_DOMAIN")
shopify_token = os.getenv("SHOPIFY_TOKEN")

print(f"DEBUG: ORDER_NUMBER={'SET' if order_number else 'MISSING'}")
print(f"DEBUG: TICKET_ID={'SET' if ticket_id else 'MISSING'}")
print(f"DEBUG: SHOPIFY_TOKEN={'SET' if shopify_token else 'MISSING'}")
print(f"DEBUG: SHOPIFY_DOMAIN={shopify_domain}")

if not order_number or not ticket_id:
    sys.exit("❌ Missing ORDER_NUMBER or TICKET_ID environment variables.")

if not shopify_token:
    sys.exit("❌ Missing SHOPIFY_TOKEN environment variable.")

print(f"🔍 Processing ticket {ticket_id} for order {order_number}")

# 1️⃣ Get latest internal comment from Zendesk
try:
    zd_url = f"https://{zendesk_subdomain}.zendesk.com/api/v2/tickets/{ticket_id}/comments.json"
    zd_res = requests.get(zd_url, auth=(f"{zendesk_email}/token", zendesk_token))
    zd_res.raise_for_status()
except requests.exceptions.HTTPError as e:
    sys.exit(f"❌ Zendesk API error: {e}")

comments = zd_res.json().get("comments", [])

# Filter for internal notes only
internal_notes = [c for c in comments if not c.get("public", True)]
if not internal_notes:
    sys.exit("⚠ No internal notes found for this ticket.")

# Get the most recent internal note
latest_note = internal_notes[-1]["body"].strip()

# Append ticket ID at the end
note_with_ticket = f"{latest_note}\n\nZendesk Ticket ID: {ticket_id}"

# 2️⃣ Find Shopify order by name
shopify_url = f"https://{shopify_domain}/admin/api/2025-01/orders.json?name={order_number}"
headers = {
    "X-Shopify-Access-Token": shopify_token,
    "Content-Type": "application/json",
}

try:
    shopify_res = requests.get(shopify_url, headers=headers)
    if shopify_res.status_code == 401:
        sys.exit("❌ Shopify API returned 401 Unauthorized — check your SHOPIFY_TOKEN and permissions.")
    shopify_res.raise_for_status()
except requests.exceptions.HTTPError as e:
    sys.exit(f"❌ Shopify API error on order fetch: {e}")

orders = shopify_res.json().get("orders", [])

if not orders:
    sys.exit(f"❌ No Shopify order found for name {order_number}")

order_id = orders[0]["id"]

# 3️⃣ Update Shopify order note
update_url = f"https://{shopify_domain}/admin/api/2025-01/orders/{order_id}.json"
payload = {"order": {"id": order_id, "note": note_with_ticket}}

try:
    update_res = requests.put(update_url, headers=headers, json=payload)
    if update_res.status_code == 401:
        sys.exit("❌ Shopify API returned 401 Unauthorized on update — check your SHOPIFY_TOKEN and permissions.")
    update_res.raise_for_status()
except requests.exceptions.HTTPError as e:
    sys.exit(f"❌ Shopify API error on order update: {e}")

print(f"✅ Added note to Shopify order {order_number}")
