import os
import requests
import datetime
import argparse

# ----------------------------
# Config
# ----------------------------
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")  # e.g. "aleena-fashion"
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SUBDOMAIN = os.getenv("SUBDOMAIN")
EMAIL = os.getenv("EMAIL")
TOKEN = os.getenv("API_TOKEN")

# ----------------------------
# Shopify Helpers
# ----------------------------
def shopify_post(query, variables=None):
    url = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2024-01/graphql.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json={"query": query, "variables": variables})
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Shopify GraphQL errors: {data['errors']}")
    return data

def get_order_by_name(order_name: str):
    query = """
    query ($query: String) {
      orders(first: 1, query: $query) {
        edges {
          node {
            id
            name
            note
          }
        }
      }
    }
    """
    data = shopify_post(query, {"query": f"name:{order_name}"})
    edges = data["data"]["orders"]["edges"]
    return edges[0]["node"] if edges else None

def shopify_update_order_note(order_gid, message_block):
    """
    Update Shopify order note by overriding the existing note.
    """
    mutation = """
    mutation orderUpdate($input: OrderInput!) {
      orderUpdate(input: $input) {
        order { id note }
        userErrors { field message }
      }
    }
    """

    variables = {"input": {"id": order_gid, "note": message_block}}
    data = shopify_post(mutation, variables)
    errs = data.get("data", {}).get("orderUpdate", {}).get("userErrors", [])
    if errs:
        raise RuntimeError(f"Shopify orderUpdate errors: {errs}")
    print("✅ Shopify order note updated successfully")

# ----------------------------
# Zendesk Helpers
# ----------------------------
def zendesk_get(path):
    url = f"https://{SUBDOMAIN}.zendesk.com/api/v2{path}"
    resp = requests.get(url, auth=(f"{EMAIL}/token", API_TOKEN))
    resp.raise_for_status()
    return resp.json()

def get_ticket(ticket_id: str):
    return zendesk_get(f"/tickets/{ticket_id}.json")["ticket"]

def get_ticket_comments(ticket_id: str):
    return zendesk_get(f"/tickets/{ticket_id}/comments.json")["comments"]

# ----------------------------
# Core Function
# ----------------------------
def sync_note(ticket_id: str):
    ticket = get_ticket(ticket_id)
    comments = get_ticket_comments(ticket_id)

    order_name = ticket["custom_fields"][0]["value"] if ticket["custom_fields"] else None
    if not order_name:
        raise RuntimeError("No Shopify order number found in ticket custom fields.")

    shop_order = get_order_by_name(order_name)
    if not shop_order:
        raise RuntimeError(f"Shopify order {order_name} not found")

    latest_comment = comments[-1]
    agent = latest_comment["author_id"]
    body = latest_comment["plain_body"].strip()
    ts = datetime.datetime.strptime(latest_comment["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    ts_date = ts.strftime("%Y-%m-%d")

    # For simplicity: just use agent id as abbrev
    agent_abbrev = str(agent)

    # Final note format
    message_block = f"#{ticket_id} | {agent_abbrev} | {ts_date}\n\n{body}"

    print(f"Debug: order_name={order_name}, agent={agent_abbrev}, ts_date={ts_date}")
    print(f"Debug: message_block:\n{message_block}")

    # Override Shopify note
    shopify_update_order_note(shop_order["id"], message_block)

    print(f"✅ Synced Zendesk ticket #{ticket_id} → Shopify order {shop_order['name']}")

# ----------------------------
# CLI
# ----------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["sync_note"])
    parser.add_argument("ticket_id")
    args = parser.parse_args()

    if args.command == "sync_note":
        sync_note(args.ticket_id)
