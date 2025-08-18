import os
import sys
import requests

def get_shopify_orders(email=None, phone=None):
    store_domain = os.getenv("SHOPIFY_STORE_DOMAIN")
    api_password = os.getenv("SHOPIFY_API_PASSWORD")

    if not store_domain or not api_password:
        print("❌ Missing Shopify credentials.")
        sys.exit(1)

    url = f"https://{store_domain}/admin/api/2025-07/orders.json"
    params = {"status": "any", "limit": 5}

    if email:
        params["email"] = email
    if phone:
        params["phone"] = phone

    response = requests.get(url, params=params, auth=("api_key", api_password))
    response.raise_for_status()
    return response.json().get("orders", [])


def add_comment_to_ticket(ticket_id, comment):
    zendesk_domain = os.getenv("ZENDESK_DOMAIN")
    zendesk_email = os.getenv("ZENDESK_EMAIL")
    zendesk_token = os.getenv("ZENDESK_API_TOKEN")

    if not zendesk_domain or not zendesk_email or not zendesk_token:
        print("❌ Missing Zendesk credentials.")
        sys.exit(1)

    url = f"https://{zendesk_domain}.zendesk.com/api/v2/tickets/{ticket_id}.json"
    headers = {"Content-Type": "application/json"}
    data = {
        "ticket": {
            "comment": {
                "body": comment,
                "public": False
            }
        }
    }

    response = requests.put(url, json=data, auth=(f"{zendesk_email}/token", zendesk_token))
    response.raise_for_status()
    return response.json()


def format_order_summary(orders):
    if not orders:
        return "❌ No orders found for this customer."

    summary_lines = []
    for order in orders:
        order_name = order.get("name", "Unknown")
        financial_status = order.get("financial_status", "Unknown")
        fulfillment_status = order.get("fulfillment_status", "Unfulfilled")
        total_price = order.get("total_price", "0.00")
        created_at = order.get("created_at", "Unknown date")

        summary_lines.append(
            f"🛒 Order {order_name} | Status: {financial_status}/{fulfillment_status} | "
            f"Total: ${total_price} | Date: {created_at}"
        )

    return "\n".join(summary_lines)


if __name__ == "__main__":
    ticket_id = os.getenv("TICKET_ID")
    customer_email = os.getenv("CUSTOMER_EMAIL")
    customer_phone = os.getenv("CUSTOMER_PHONE")

    if not ticket_id:
        print("❌ Missing required TICKET_ID.")
        sys.exit(1)

    if not (customer_email or customer_phone):
        print("❌ Missing customer identifier (email/phone).")
        sys.exit(1)

    try:
        orders = get_shopify_orders(email=customer_email, phone=customer_phone)
        summary = format_order_summary(orders)
        result = add_comment_to_ticket(ticket_id, summary)
        print(f"✅ Added Shopify order lookup result to Zendesk ticket {ticket_id}")
    except requests.HTTPError as e:
        print(f"❌ API Error: {e.response.status_code} - {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        sys.exit(1)
