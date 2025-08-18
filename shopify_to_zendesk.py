import os
import sys
import requests
import re

# ----------------- Helper Functions -----------------
def get_env_var(name):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()

def normalize_phone(phone):
    """Remove all non-digit characters for comparison"""
    if not phone:
        return ""
    return re.sub(r"\D", "", phone)

# ----------------- Environment Variables -----------------
SHOPIFY_STORE_DOMAIN = get_env_var("SHOPIFY_SHOP_DOMAIN")  # e.g., 'shopaleena'
SHOPIFY_ACCESS_TOKEN = get_env_var("SHOPIFY_ACCESS_TOKEN")
ZENDESK_EMAIL = get_env_var("ZENDESK_EMAIL")
ZENDESK_API_TOKEN = get_env_var("ZENDESK_API_TOKEN")
ZENDESK_DOMAIN = get_env_var("ZENDESK_DOMAIN")

TICKET_ID = get_env_var("TICKET_ID")
CUSTOMER_EMAIL = get_env_var("CUSTOMER_EMAIL")
CUSTOMER_PHONE = get_env_var("CUSTOMER_PHONE")
ORDER_NAME = get_env_var("ORDER_NAME")  # optional, like A12345

# ----------------- Validate Credentials -----------------
missing = []
for var, name in [(SHOPIFY_STORE_DOMAIN, "SHOPIFY_STORE_DOMAIN"),
                  (SHOPIFY_ACCESS_TOKEN, "SHOPIFY_ACCESS_TOKEN"),
                  (ZENDESK_EMAIL, "ZENDESK_EMAIL"),
                  (ZENDESK_API_TOKEN, "ZENDESK_API_TOKEN"),
                  (ZENDESK_DOMAIN, "ZENDESK_DOMAIN")]:
    if not var:
        missing.append(name)

if missing:
    print(f"❌ Missing required credentials: {', '.join(missing)}")
    sys.exit(1)

if not TICKET_ID:
    print("❌ Missing TICKET_ID (required to update Zendesk).")
    sys.exit(1)

if not (CUSTOMER_EMAIL or CUSTOMER_PHONE or ORDER_NAME):
    print("❌ Missing customer identifier (need CUSTOMER_EMAIL, CUSTOMER_PHONE, or ORDER_NAME).")
    sys.exit(1)

print("✅ Credentials loaded successfully.")
print(f"Debug Info: STORE={SHOPIFY_STORE_DOMAIN}, ZD={ZENDESK_DOMAIN}, TICKET={TICKET_ID}")

# ----------------- Shopify API Request -----------------
shopify_url = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/2025-07/orders.json"
headers = {"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN}

# Base query params
query_params = {"status": "any", "limit": 50}
if CUSTOMER_EMAIL:
    query_params["email"] = CUSTOMER_EMAIL
if ORDER_NAME:
    query_params["name"] = ORDER_NAME

# Fetch orders with pagination
orders = []
page_info = None

try:
    while True:
        params = query_params.copy()
        if page_info:
            params['page_info'] = page_info
        
        resp = requests.get(shopify_url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json().get("orders", [])
        orders.extend(data)

        # Check for pagination
        link_header = resp.headers.get("Link")
        if link_header and 'rel="next"' in link_header:
            match = re.search(r'page_info=([^&>]+)', link_header)
            page_info = match.group(1) if match else None
            if not page_info:
                break
        else:
            break

    # Manual filtering by phone if provided
    if CUSTOMER_PHONE:
        customer_phone_norm = normalize_phone(CUSTOMER_PHONE)
        orders = [o for o in orders if normalize_phone(o.get("phone")) == customer_phone_norm]

except requests.exceptions.RequestException as e:
    print(f"❌ Shopify API error: {e}")
    sys.exit(1)

# ----------------- Build Zendesk Note -----------------
if not orders:
    note = f"No Shopify orders found for {CUSTOMER_EMAIL or CUSTOMER_PHONE or ORDER_NAME}"
else:
    lines = [f"📦 Shopify orders for {CUSTOMER_EMAIL or CUSTOMER_PHONE or ORDER_NAME}:"]
    for order in orders:
        lines.append(
            f"- Order {order.get('name')} (ID: {order.get('id')}) | "
            f"Created: {order.get('created_at')} | "
            f"Total: {order.get('total_price')} {order.get('currency')}"
        )
        for item in order.get("line_items", []):
            lines.append(f"    • {item.get('quantity')} x {item.get('name')} @ {item.get('price')} {order.get('currency')}")
    note = "\n".join(lines)

print(f"ℹ️ Adding note to Zendesk ticket {TICKET_ID}:\n{note}")

# ----------------- Update Zendesk -----------------
zd_url = f"https://{ZENDESK_DOMAIN}.zendesk.com/api/v2/tickets/{TICKET_ID}.json"
zd_payload = {"ticket": {"comment": {"body": note, "public": False}}}

try:
    zd_resp = requests.put(
        zd_url,
        json=zd_payload,
        auth=(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN),
        timeout=20
    )
    zd_resp.raise_for_status()
    print(f"✅ Successfully updated Zendesk ticket {TICKET_ID}")
except requests.exceptions.RequestException as e:
    print(f"❌ Zendesk API error: {e}")
    sys.exit(1)
