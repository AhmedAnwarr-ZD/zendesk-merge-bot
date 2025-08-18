import os
import sys
import requests

def get_env_var(name):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()

SHOPIFY_STORE_DOMAIN = get_env_var("SHOPIFY_SHOP_DOMAIN")
SHOPIFY_API_PASSWORD = get_env_var("SHOPIFY_ACCESS_TOKEN")
ZENDESK_EMAIL = get_env_var("ZENDESK_EMAIL")
ZENDESK_API_TOKEN = get_env_var("ZENDESK_API_TOKEN")
ZENDESK_DOMAIN = get_env_var("ZENDESK_DOMAIN")

TICKET_ID = get_env_var("TICKET_ID")
CUSTOMER_EMAIL = get_env_var("CUSTOMER_EMAIL")
CUSTOMER_PHONE = get_env_var("CUSTOMER_PHONE")

# Fail early if required creds are missing
missing = []
if not SHOPIFY_STORE_DOMAIN: missing.append("SHOPIFY_STORE_DOMAIN")
if not SHOPIFY_API_PASSWORD: missing.append("SHOPIFY_API_PASSWORD")
if not ZENDESK_EMAIL: missing.append("ZENDESK_EMAIL")
if not ZENDESK_API_TOKEN: missing.append("ZENDESK_API_TOKEN")
if not ZENDESK_DOMAIN: missing.append("ZENDESK_DOMAIN")

if missing:
    print(f"❌ Missing required credentials: {', '.join(missing)}")
    sys.exit(1)

if not TICKET_ID:
    print("❌ Missing TICKET_ID (required to update Zendesk).")
    sys.exit(1)

if not (CUSTOMER_EMAIL or CUSTOMER_PHONE):
    print("❌ Missing customer identifier (need CUSTOMER_EMAIL or CUSTOMER_PHONE).")
    sys.exit(1)

print("✅ Credentials loaded successfully.")
print(f"Debug Info: STORE={SHOPIFY_STORE_DOMAIN}, ZD={ZENDESK_DOMAIN}, TICKET={TICKET_ID}")

# Shopify API request
session = requests.Session()
session.auth = ("", SHOPIFY_API_PASSWORD)

query_params = {"status": "any", "limit": 5}
if CUSTOMER_EMAIL:
    query_params["email"] = CUSTOMER_EMAIL
elif CUSTOMER_PHONE:
    query_params["phone"] = CUSTOMER_PHONE

shopify_url = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/2025-07/orders.json"

try:
    resp = session.get(shopify_url, params=query_params, timeout=20, verify=False)
    resp.raise_for_status()
    orders = resp.json().get("orders", [])
except requests.exceptions.RequestException as e:
    print(f"❌ Shopify API error: {e}")
    sys.exit(1)

if not orders:
    note = f"No Shopify orders found for {CUSTOMER_EMAIL or CUSTOMER_PHONE}"
else:
    order = orders[0]
    order_name = order.get("name", "Unknown")
    order_id = order.get("id")
    note = f"Found Shopify order: {order_name} (ID: {order_id})"

print(f"ℹ️ Adding note to Zendesk ticket {TICKET_ID}: {note}")

# Update Zendesk
zd_url = f"https://{ZENDESK_DOMAIN}.zendesk.com/api/v2/tickets/{TICKET_ID}.json"
zd_payload = {"ticket": {"comment": {"body": note}}}

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
