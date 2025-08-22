import os
import sys
import re
from datetime import datetime
import requests

# ================== ENV ==================
EMAIL = os.getenv("EMAIL")                   # Zendesk email used with token
API_TOKEN = os.getenv("API_TOKEN")           # Zendesk API token
SUBDOMAIN = os.getenv("SUBDOMAIN")           # Zendesk subdomain

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")   # Shopify Admin API token
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN") # Shopify domain

API_VERSION = "2025-07"
ZENDESK_API_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
SHOPIFY_GRAPHQL_URL = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/{API_VERSION}/graphql.json"

SHOPIFY_HEADERS = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    "Content-Type": "application/json",
}

# ================== HELPERS ==================
def zendesk_get(url):
    resp = requests.get(url, auth=(f"{EMAIL}/token", API_TOKEN))
    resp.raise_for_status()
    return resp.json()

def shopify_post(query, variables=None):
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = requests.post(SHOPIFY_GRAPHQL_URL, headers=SHOPIFY_HEADERS, json=payload)
    resp.raise_for_status()
    return resp.json()

# ================== ZENDESK ==================
ORDER_PATTERN = re.compile(r"\b[Aa]\d+\b")

def extract_order_name(text):
    if not text:
        return None
    match = ORDER_PATTERN.search(text)
    if match:
        return "A" + match.group(0)[1:]  # normalize to uppercase A
    return None

def get_latest_internal_note(ticket_id):
    audits_url = f"{ZENDESK_API_URL}/tickets/{ticket_id}/audits.json"
    audits = zendesk_get(audits_url).get("audits", [])
    latest = None
    for audit in audits:
        created_at = audit.get("created_at")
        for event in audit.get("events", []):
            if event.get("type") == "Comment" and not event.get("public", True):
                body = event.get("body") or ""
                order_name = extract_order_name(body)
                author_id = event.get("author_id")
                latest = {
                    "order_name": order_name,
                    "body": body,
                    "author_id": author_id,
                    "created_at": created_at,
                }
    if not latest:
        return None

    # fetch agent name
    agent_name = "Unknown Agent"
    try:
        if latest.get("author_id"):
            u = zendesk_get(f"{ZENDESK_API_URL}/users/{latest['author_id']}.json")
            agent_name = u.get("user", {}).get("name", agent_name)
    except:
        pass
    latest["author_name"] = agent_name
    return latest

# ================== SHOPIFY ==================
def shopify_find_order(order_name):
    query = """
    query($q: String!) {
      orders(first: 1, query: $q) {
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
    variables = {"q": f"name:{order_name}"}
    data = shopify_post(query, variables)
    edges = data.get("data", {}).get("orders", {}).get("edges", [])
    if not edges:
        return None
    node = edges[0]["node"]
    return {"id": node["id"], "name": node["name"], "note": node.get("note") or ""}

def shopify_update_order_note(order_gid, old_note, message_block):
    combined = f"{old_note}\n{message_block}".strip() if old_note else message_block
    mutation = """
    mutation orderUpdate($input: OrderInput!) {
      orderUpdate(input: $input) {
        order { id note }
        userErrors { field message }
      }
    }
    """
    variables = {"input": {"id": order_gid, "note": combined}}
    data = shopify_post(mutation, variables)
    errs = data.get("data", {}).get("orderUpdate", {}).get("userErrors", [])
    if errs:
        raise RuntimeError(f"Shopify orderUpdate errors: {errs}")
    print("✅ Shopify order note updated successfully")

# ================== MAIN ==================
def sync_note(ticket_id: str):
    print(f"Debug: syncing ticket_id={ticket_id}")
    note = get_latest_internal_note(ticket_id)
    if not note:
        print(f"❌ No internal note found in Zendesk ticket {ticket_id}")
        return

    order_name = note.get("order_name")
    if not order_name:
        print(f"❌ Could not detect Shopify order name in ticket {ticket_id}")
        return

    shop_order = shopify_find_order(order_name)
    if not shop_order:
        print(f"❌ Shopify order not found for name {order_name}")
        return

    created_at = note.get("created_at") or ""
    try:
        ts_date = datetime.fromisoformat(created_at.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except:
        ts_date = created_at.split("T")[0]

    agent = note.get("author_name", "Unknown Agent")
    body = note.get("body").strip()

    # remove order number from start if present
    if order_name and body.startswith(order_name):
        body = body[len(order_name):].strip()

    # Abbreviate agent name: First + first letter of last
    parts = agent.split()
    agent_abbrev = f"{parts[0]} {parts[1][0]}" if len(parts) >= 2 else parts[0]

    # Build final note
    message_block = f"#{ticket_id} | {agent_abbrev} | {ts_date}\n\n{body}"

    # Debug info
    print(f"Debug: order_name={order_name}, agent={agent_abbrev}, ts_date={ts_date}")
    print(f"Debug: message_block:\n{message_block}")

    # Update Shopify order note
    shopify_update_order_note(shop_order["id"], shop_order["note"], message_block)

    print(f"✅ Synced Zendesk ticket #{ticket_id} → Shopify order {shop_order['name']}")

# ================== CLI ==================
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python script.py sync_note <ticket_id>")
        sys.exit(1)

    action = sys.argv[1]
    if action != "sync_note":
        print(f"Action '{action}' not supported.")
        sys.exit(1)

    ticket_id = sys.argv[2]
    sync_note(ticket_id)
