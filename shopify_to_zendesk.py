import os
import sys
import requests
import re

def get_env_var(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"❌ Missing required environment variable: {name}")
    return value

def get_shopify_domain() -> str:
    shop_subdomain = get_env_var("SHOPIFY_SHOP_DOMAIN")
    return f"{shop_subdomain}.myshopify.com"

def get_shopify_headers() -> dict:
    access_token = get_env_var("SHOPIFY_ACCESS_TOKEN")
    return {"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"}

def fetch_orders_by_identifier(identifier: str):
    """
    Identifier can be:
      - Order name (e.g. A266626)
      - Phone number (e.g. 966550009712)
      - Email address
    """
    shop_domain = get_shopify_domain()
    headers = get_shopify_headers()

    base_url = f"https://{shop_domain}/admin/api/2025-07/orders.json?status=any&limit=50"

    if identifier.isdigit() or identifier.replace(" ", "").isdigit():
        clean_phone = identifier.replace(" ", "")
        url = f"{base_url}&phone={clean_phone}"
    elif "@" in identifier:
        url = f"{base_url}&email={identifier}"
    else:
        url = f"{base_url}&name={identifier}"

    print(f"🔎 Fetching Shopify orders using: {url}")

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        orders = response.json().get("orders", [])
        if not orders:
            print("❌ No orders found for identifier:", identifier)
            return []
        return orders
    except requests.exceptions.RequestException as e:
        print("❌ Shopify API request failed:", e)
        return []

def format_order(order: dict) -> str:
    """Format a single order into a readable text block."""
    details = []
    details.append(f"🛒 Order {order.get('name')} (ID: {order.get('id')})")
    details.append(f"📅 Created: {order.get('created_at')}")
    details.append(f"💳 Financial Status: {order.get('financial_status')}")
    details.append(f"🚚 Fulfillment Status: {order.get('fulfillment_status')}")
    details.append(f"📧 Email: {order.get('email')}")
    details.append(f"📞 Phone: {order.get('phone')}")
    details.append("🧾 Line Items:")
    for item in order.get("line_items", []):
        details.append(
            f"   - {item.get('quantity')}x {item.get('title')} @ {item.get('price')} {order.get('currency')}"
        )
    details.append(f"💰 Total Price: {order.get('total_price')} {order.get('currency')}")
    return "\n".join(details)

def main():
    if len(sys.argv) < 2:
        print("Usage: python shopify_to_zendesk.py <identifier>")
        sys.exit(1)

    identifier = sys.argv[1]
    orders = fetch_orders_by_identifier(identifier)

    if orders:
        print(f"✅ Found {len(orders)} order(s):\n")
        for order in orders:
            print(format_order(order))
            print("-" * 40)
    else:
        print("❌ No matching orders found.")

if __name__ == "__main__":
    main()
