import os
import sys
import requests
import re

# ------------------------------
# Load environment variables
# ------------------------------
SHOPIFY_STORE_DOMAIN = os.getenv("SHOPIFY_STORE_DOMAIN")
SHOPIFY_API_PASSWORD = os.getenv("SHOPIFY_API_PASSWORD")
ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL")
ZENDESK_API_TOKEN = os.getenv("ZENDESK_API_TOKEN")
ZENDESK_DOMAIN = os.getenv("ZENDESK_DOMAIN")

# Optional fallback identifiers
TICKET_ID = os.getenv("TICKET_ID")
CUSTOMER_EMAIL = os.getenv("CUSTOMER_EMAIL")
CUSTOMER_PHONE = os.getenv("CUSTOMER_PHONE")

# ------------------------------
# Validate credentials
# ------------------------------
if not all([SHOPIFY_STORE_DOMAIN, SHOPIFY_API_PASSWORD, ZENDESK_EMAIL, ZENDESK_API_TOKEN, ZENDESK_DOMAIN]):
    print("❌ Missing Shopify or Zendesk credentials.")
    sys.exit(1)

# ------------------------------
# Get identifier from args or env
# ------------------------------
identifier = None
if len(sys.argv) > 1 and sys.argv[1].strip() != "":
    identifier = sys.argv[1].strip()
else:
    # Fall back to env variables
    identifier = CUSTOMER_EMAIL or CUSTOMER_PHONE or TICKET_ID

if not identifier:
    print("❌ Missing identifier (email, phone, or ticket id).")
    sys.exit(1)

# ------------------------------
# Shopify API call
# ------------------------------
SHOPIFY_URL = f"https://{SHOPIFY_STORE_DOMAIN}.myshopify.com/admin/api/2025-07/orders.json"

params = {"status": "any", "limit": 50}

if re.match(r"^\d+$", identifier):  # Order ID (numeric)
    params["name"] = identifier
elif "@" in identifier:  # Email
    params["email"] = identifier
elif identifier.startswith("966"):  # Phone number
    params["phone"] = identifier
else:
    params["name"] = identifier  # fallback

try:
    response = requests.get(
        SHOPIFY_URL,
        auth=("admin", SHOPIFY_API_PASSWORD),
        params=params,
        timeout=20,
        verify=False  # ⚠️ skip SSL check if needed
    )
    response.raise_for_status()
except requests.exceptions.RequestException as e:
    print(f"❌ Shopify API request failed: {e}")
    sys.exit(1)

orders = response.json().get("orders", [])

if not orders:
    print(f"⚠️ No orders found for identifier: {identifier}")
    sys.exit(0)

# ------------------------------
# Prepare Zendesk comment
# ------------------------------
order_comments = []
for order in orders:
    order_id = order.get("name", "N/A")
    order_total = order.get("total_price", "0")
    order_status = order.get("fulfillment_status", "Unfulfilled")
    order_comments.append(f"🛒 Order {order_id} | Total: {order_total} | Status: {order_status}")

comment_body = "\n".join(order_comments)

# ------------------------------
# Post comment to Zendesk ticket
# ------------------------------
if not TICKET_ID:
    print("⚠️ No Zendesk TICKET_ID provided, skipping Zendesk update.")
    print("Preview Comment:\n", comment_body)
    sys.exit(0)

zendesk_url = f"https://{ZENDESK_DOMAIN}.zendesk.com/api/v2/tickets/{TICKET_ID}.json"
payload = {
    "ticket": {
        "comment": {
            "body": comment_body,
            "public": False
        }
    }
}

try:
    zd_resp = requests.put(
        zendesk_url,
        json=payload,
        auth=(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN),
        timeout=20
    )
    zd_resp.raise_for_status()
    print(f"✅ Successfully added Shopify order details to Zendesk ticket {TICKET_ID}")
except requests.exceptions.RequestException as e:
    print(f"❌ Failed to update Zendesk ticket: {e}")
    sys.exit(1)
