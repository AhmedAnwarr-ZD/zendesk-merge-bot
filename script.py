from urllib.parse import quote

def find_order_id_by_name(order_name):
    """
    Fetch Shopify orders and match by order name.
    Handles special characters like '#' via URL encoding.
    """
    encoded_name = quote(order_name, safe='')  # encode special characters

    url = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2024-01/orders.json?status=any&name={encoded_name}&limit=250"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }

    resp = requests.get(url, headers=headers, verify=False)  # skip SSL for GitHub Actions
    resp.raise_for_status()
    orders = resp.json().get("orders", [])

    for order in orders:
        # Compare ignoring case, strip # if necessary
        if order.get("name", "").lower() == order_name.lower():
            return order["id"]

    return None
