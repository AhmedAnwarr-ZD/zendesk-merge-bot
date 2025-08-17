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

def fetch_order_by_identifier(identifier: str):
    """
    Identifier can be:
      - Order name (e.g. A266626)
      - Phone number (e.g. 966550009712, with or without spaces)
      - Email address
    """
    shop_domain = get_shopify_domain()
    headers = get_shopify_headers()

    base_url = f"https://{shop_domain}/admin/api/2025-07/orders.json?status=any&limit=5"

    # Check what kind of identifier it is
    if identifier.isdigit() or identifier.replace(" ", "").isdigit():
        # Treat as phone number, remove spaces
        clean_phone = identifier.replace(" ", "")
        url = f"{base_url}&phone={clean_phone}"
    elif "@" in identifier:
        # Treat as email
        url = f"{base_url}&email={identifier}"
    else:
        # Treat as Shopify order name
        url = f"{base_url}&name={identifier}"

    print(f"🔎 Fetching Shopify order using: {url}")

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        orders = response.json().get("orders", [])
        if not orders:
            print("❌ No orders found for identifier:", identifier)
            return None
        return orders[0]  # return first matched order
    except requests.exceptions.RequestException as e:
        print("❌ Shopify API request failed:", e)
        return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <identifier>")
        sys.exit(1)

    identifier = sys.argv[1]
    order = fetch_order_by_identifier(identifier)

    if order:
        print("✅ Found Order:")
        print("ID:", order.get("id"))
        print("Name:", order.get("name"))
        print("Email:", order.get("email"))
        print("Phone:", order.get("phone"))
    else:
        print("❌ No matching order found.")

if __name__ == "__main__":
    main()
