import os
import requests

order_number = os.getenv("ORDER_NUMBER")
ticket_id = os.getenv("TICKET_ID")
zendesk_subdomain = os.getenv("ZENDESK_SUBDOMAIN")
zendesk_email = os.getenv("ZENDESK_EMAIL")
zendesk_token = os.getenv("ZENDESK_TOKEN")
shopify_domain = os.getenv("SHOPIFY_DOMAIN")
shopify_token = os.getenv("SHOPIFY_TOKEN")

if not order_number or not ticket_id:
    raise SystemExit("❌ Missing ORDER_NUMBER or TICKET_ID")

print(f"🔍 Processing ticket {ticket_id} for order {order_number}")

# 1️⃣ Get latest internal comment from Zendesk
zd_url = f"https://{zendesk_subdomain}.zendesk.com/api/v2/tickets/{ticket_id}/comments.json"
zd_res = requests.get(zd_url, auth=(f"{zendesk_email}/token", zendesk_token))
zd_res.raise_for_status()
comments = zd_res.json().get("comments", [])

# Filter for internal notes only
internal_notes = [c for c in comments if not c["public"]]
if not internal_notes:
    raise SystemExit("⚠ No internal notes found for this ticket.")

# Get the most recent internal note
latest_note = internal_notes[-1]["body"].strip()

# Append ticket ID at the end
note_with_ticket = f"{latest_note}\n\nZendesk Ticket ID: {ticket_id}"

# 2️⃣ Find Shopify order by name
shopify_url = f"https://{shopify_domain}/admin/api/2025-01/orders.json?name={order_number}"
headers = {"X-Shopify-Access-Token": shopify_token}
shopify_res = requests.get(shopify_url, headers=headers)
shopify_res.raise_for_status()
orders = shopify_res.json().get("orders", [])

if not orders:
    raise SystemExit(f"❌ No Shopify order found for name {order_number}")

order_id = orders[0]["id"]

# 3️⃣ Update Shopify order note
update_url = f"https://{shopify_domain}/admin/api/2025-01/orders/{order_id}.json"
payload = {"order": {"id": order_id, "note": note_with_ticket}}
update_res = requests.put(update_url, headers=headers, json=payload)
update_res.raise_for_status()

print(f"✅ Added note to Shopify order {order_number}")
