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

print("✅ Credentials loaded successfully.")
print(f"Debug Info: STORE={SHOPIFY_STORE_DOMAIN}, ZD={ZENDESK_DOMAIN}, TICKET={TICKET_ID}")

# ----------------- Fetch Zendesk Ticket -----------------
zd_ticket_url = f"https://{ZENDESK_DOMAIN}.zendesk.com/api/v2/tickets/{TICKET_ID}.json"

try:
    resp = requests.get(
        zd_ticket_url,
        auth=(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN),
        timeout=20
    )
    resp.raise_for_status()
    ticket = resp.json().get("ticket", {})
except requests.exceptions.RequestException as e:
    print(f"❌ Zendesk API error fetching ticket: {e}")
    sys.exit(1)

# ----------------- Check Ticket Type -----------------
channel = ticket.get("via", {}).get("channel")
if channel not in ["web", "email", "whatsapp"]:
    print(f"ℹ️ Ticket type '{channel}' not supported, skipping.")
    sys.exit(0)

# ----------------- Find End-User Info from Comments -----------------
end_user_email = None
end_user_phone = None
full_name = None

try:
    comments_url = f"https://{ZENDESK_DOMAIN}.zendesk.com/api/v2/tickets/{TICKET_ID}/comments.json"
    resp = requests.get(comments_url, auth=(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN), timeout=20)
    resp.raise_for_status()
    comments = resp.json().get("comments", [])
except requests.exceptions.RequestException as e:
    print(f"❌ Zendesk API error fetching comments: {e}")
    sys.exit(1)

# Look for internal note with "info"
for comment in comments:
    if not comment.get("public") and "info" in comment.get("body", "").lower():
        full_name = comment.get("author", {}).get("name")
        end_user_email = comment.get("author", {}).get("email")
        end_user_phone = comment.get("author", {}).get("phone")
        break

if not (end_user_email or end_user_phone):
    print("❌ No end-user info found in internal notes containing 'info'.")
    sys.exit(0)

print(f"ℹ️ End-user found: {full_name} | {end_user_email} | {end_user_phone}")

# ----------------- Fetch Shopify Orders -----------------
shopify_url = f"https://{SHOPIFY_STORE_DOMAIN}.myshopify.com/admin/api/2025-07/orders.json"
headers = {"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN}

query_params = {"status": "any", "limit": 50}
if end_user_email:
    query_params["email"] = end_user_email

orders = []
page_info = None

try:
    while True:
        if page_info:
            params = {"page_info": page_info}  # must only include page_info
        else:
            params = query_params.copy()

        resp = requests.get(shopify_url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json().get("orders", [])
        orders.extend(data)

        # Next page check
        link_header = resp.headers.get("Link")
        if link_header and 'rel="next"' in link_header:
            match = re.search(r'page_info=([^&>]+)', link_header)
            page_info = match.group(1) if match else None
            if not page_info:
                break
        else:
            break

    # Manual filtering by phone
    if end_user_phone:
        phone_norm = normalize_phone(end_user_phone)
        orders = [o for o in orders if normalize_phone(o.get("phone")) == phone_norm]

except requests.exceptions.RequestException as e:
    print(f"❌ Shopify API error: {e}")
    sys.exit(1)

# ----------------- Build Zendesk Note -----------------
if not orders:
    note = f"No Shopify orders found for {full_name or end_user_email or end_user_phone}"
else:
    lines = [
        f"📦 Shopify Customer Profile:",
        f"Full Name: {full_name or 'N/A'}",
        f"Email: {end_user_email or 'N/A'}",
        f"Phone: {end_user_phone or 'N/A'}",
        f"Number of Orders: {len(orders)}",
        "",
        "Orders:"
    ]
    for order in orders[:5]:  # limit to latest 5 orders
        order_name = order.get("name")
        order_id = order.get("id")
        order_link = f"https://{SHOPIFY_STORE_DOMAIN}.myshopify.com/admin/orders/{order_id}"
        order_email = order.get("email", end_user_email or "N/A")
        order_phone = order.get("phone", end_user_phone or "N/A")
        lines.append(f"- [{order_name}]({order_link}) - Email: {order_email} - Phone: {order_phone}")
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
