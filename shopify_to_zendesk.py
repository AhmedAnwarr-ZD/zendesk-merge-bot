import os
import requests
from datetime import datetime

# ================== ENV ==================
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")
API_VERSION = "2025-07"

ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL")
ZENDESK_TOKEN = os.getenv("ZENDESK_TOKEN")
ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN")

SHOPIFY_GRAPHQL_URL = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/{API_VERSION}/graphql.json"
ZENDESK_TICKET_URL = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets"

HEADERS_SHOPIFY = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    "Content-Type": "application/json",
}
HEADERS_ZENDESK = {
    "Content-Type": "application/json",
}

# ================== Shopify Functions ==================
def shopify_post(query, variables=None):
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = requests.post(SHOPIFY_GRAPHQL_URL, headers=HEADERS_SHOPIFY, json=payload)
    resp.raise_for_status()
    return resp.json()

def get_customer_orders(customer_input):
    # Determine if input is phone or email
    if customer_input.isdigit() and customer_input.startswith("966"):
        query_string = f"phone:{customer_input}"
    else:
        query_string = f"email:{customer_input}"
    
    query = """
    query getOrdersByCustomer($query: String!) {
      orders(first: 50, query: $query, sortKey: CREATED_AT, reverse: true) {
        edges {
          node {
            name
            createdAt
            financialStatus
            fulfillmentStatus
            totalPriceSet { shopMoney { amount currencyCode } }
            shippingLines {
              trackingNumbers
              trackingUrls
            }
            lineItems(first:50){
              edges{
                node{
                  sku
                  name
                  quantity
                  originalTotalSet { shopMoney { amount currencyCode } }
                }
              }
            }
          }
        }
      }
    }
    """
    variables = {"query": query_string}
    data = shopify_post(query, variables)
    orders = data.get("data", {}).get("orders", {}).get("edges", [])
    return [o["node"] for o in orders]

# ================== Format Note ==================
def format_orders_for_zendesk(orders):
    notes = []
    for o in orders:
        order_name = o.get("name")
        created_at = o.get("createdAt", "")
        try:
            created_at = datetime.fromisoformat(created_at.replace("Z","+00:00")).strftime("%d-%m-%Y")
        except:
            pass
        fulfillment = o.get("fulfillmentStatus") or "N/A"
        payment = o.get("financialStatus") or "N/A"

        # Delivery tracking
        delivery_awb = ""
        for sl in o.get("shippingLines", []):
            if sl.get("trackingNumbers"):
                nums = ", ".join(sl["trackingNumbers"])
                urls = sl.get("trackingUrls", [])
                link = urls[0] if urls else ""
                delivery_awb = f"[{nums}]({link})" if link else nums

        # Line items
        skus = []
        for li in o.get("lineItems", {}).get("edges", []):
            n = li["node"]
            amount = n.get("originalTotalSet", {}).get("shopMoney", {}).get("amount","0.00")
            currency = n.get("originalTotalSet", {}).get("shopMoney", {}).get("currencyCode","SAR")
            skus.append(f"{n['sku']} x {n['quantity']} - {amount} {currency}")

        # Paid amount
        total = o.get("totalPriceSet", {}).get("shopMoney", {}).get("amount","0.00")
        currency = o.get("totalPriceSet", {}).get("shopMoney", {}).get("currencyCode","SAR")

        note = f"""
order name [{order_name}]
created at [{created_at}]
{fulfillment} | {payment} | delivery/return status
delivery tracking AWB {delivery_awb}
return AWB 
"""
        for idx, sku_line in enumerate(skus, start=1):
            note += f"SKU #{idx}: {sku_line}\n"
        note += f"paid amount [{total} {currency}]\n"
        note += "-"*68
        notes.append(note.strip())
    return "\n".join(notes)

# ================== Zendesk ==================
def post_internal_note(ticket_id, note_text):
    url = f"{ZENDESK_TICKET_URL}/{ticket_id}.json"
    data = {
        "ticket": {
            "comment": {
                "body": note_text,
                "public": False
            }
        }
    }
    resp = requests.put(url, headers=HEADERS_ZENDESK, auth=(ZENDESK_EMAIL+"/token", ZENDESK_TOKEN), json=data)
    resp.raise_for_status()
    print(f"✅ Internal note posted to ticket {ticket_id}")

# ================== Main ==================
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python shopify_to_zendesk.py <ticket_id> <customer_email_or_phone>")
        sys.exit(1)

    ticket_id = sys.argv[1]
    customer_input = sys.argv[2]

    orders = get_customer_orders(customer_input)
    if not orders:
        print("❌ No orders found for customer")
        sys.exit(0)

    note_text = format_orders_for_zendesk(orders)
    post_internal_note(ticket_id, note_text)
