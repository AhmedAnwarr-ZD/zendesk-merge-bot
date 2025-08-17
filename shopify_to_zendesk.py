import os
import re
import requests

SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_API_PASSWORD = os.getenv("SHOPIFY_API_PASSWORD")
SHOPIFY_STORE_DOMAIN = os.getenv("SHOPIFY_STORE_DOMAIN")
ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL")
ZENDESK_API_TOKEN = os.getenv("ZENDESK_API_TOKEN")
ZENDESK_DOMAIN = os.getenv("ZENDESK_DOMAIN")

TICKET_ID = os.getenv("TICKET_ID")
CUSTOMER_EMAIL = os.getenv("CUSTOMER_EMAIL")
CUSTOMER_PHONE = os.getenv("CUSTOMER_PHONE")

def clean_phone(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)  # remove spaces, dashes, etc.
    return digits

def get_orders_by_email(email):
    url = f"https://{SHOPIFY_API_KEY}:{SHOPIFY_API_PASSWORD}@{SHOPIFY_STORE_DOMAIN}/admin/api/2025-07/orders.json"
    params = {"status": "any", "email": email, "limit": 5}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json().get("orders", [])

def get_orders_by_phone(phone):
    url = f"https://{SHOPIFY_API_KEY}:{SHOPIFY_API_PASSWORD}@{SHOPIFY_STORE_DOMAIN}/admin/api/2025-07/orders.json"
    params = {"status": "any", "phone": phone, "limit": 5}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json().get("orders", [])

def format_orders(orders):
    if not orders:
        return "❌ No orders found."
    lines = []
    for o in orders:
        lines.append(f"#{o['name']} | {o['created_at'][:10]} | {o['financial_status']} | {o['fulfillment_status'] or 'Unfulfilled'}")
    return "\n".join(lines)

def post_to_zendesk(ticket_id, message):
    url = f"https://{ZENDESK_DOMAIN}/api/v2/tickets/{ticket_id}.json"
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
    payload = {
        "ticket": {
            "comment": {
                "body": message,
                "public": False
            }
        }
    }
    resp = requests.put(url, json=payload, auth=auth)
    resp.raise_for_status()

def main():
    email_orders, phone_orders = [], []
    if CUSTOMER_EMAIL:
        email_orders = get_orders_by_email(CUSTOMER_EMAIL.strip())
    if CUSTOMER_PHONE:
        phone_orders = get_orders_by_phone(clean_phone(CUSTOMER_PHONE))

    combined_orders = email_orders + phone_orders
    if not combined_orders:
        message = f"No orders found for Email: {CUSTOMER_EMAIL}, Phone: {CUSTOMER_PHONE}"
    else:
        message = "Orders found:\n" + format_orders(combined_orders)

    post_to_zendesk(TICKET_ID, message)

if __name__ == "__main__":
    main()
