import os
import requests

# Env vars
order_number = os.getenv("ORDER_NUMBER")
ticket_id = os.getenv("TICKET_ID")
zendesk_subdomain = os.getenv("ZENDESK_SUBDOMAIN")
zendesk_email = os.getenv("ZENDESK_EMAIL")
zendesk_token = os.getenv("ZENDESK_TOKEN")
shopify_domain = os.getenv("SHOPIFY_DOMAIN")
shopify_token = os.getenv("SHOPIFY_TOKEN")

# 1. Get first requester message from Zendesk
zd_url = f"https://{zendesk_subdomain}.zendesk.com/api/v2/tickets/{ticket_id}/comments.json"
zd_res = requests.get(zd_url, auth=(f"{zendesk_email}/token", zendesk_token))
zd_res.raise_for_status()
comments = zd_res.json()["comments"]
first_msg = comments[0]["body"]

# 2. Find Shopify order ID
shopify_url = f"https://{shopify_domain}/admin/api/2025-01/orders.json?name={order_number}"
headers = {"X-Shopify-Access-Token": shopify_token}
shopify_res = requests.get(shopify_url, headers=headers)
shopify_res.raise_for_status()
orders = shopify_res.json()["orders"]
if not orders:
    raise SystemExit(f"No order found for {order_number}")
order_id = orders[0]["id"]

# 3. Add note to Shopify order
update_url = f"https://{shopify_domain}/admin/api/2025-01/orders/{order_id}.json"
payload = {"order": {"id": order_id, "note": first_msg}}
update_res = requests.put(update_url, headers=headers, json=payload)
update_res.raise_for_status()

print(f"✅ Added note to Shopify order {order_number}")
