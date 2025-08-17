import os
import sys
import requests
import re
from dotenv import load_dotenv
from datetime import datetime

# Load local .env if present
load_dotenv()

# Environment variables
EMAIL = os.getenv("EMAIL")
API_TOKEN = os.getenv("API_TOKEN")
SUBDOMAIN = os.getenv("SUBDOMAIN")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")

ZENDESK_API_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
SHOPIFY_GRAPHQL_URL = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2025-07/graphql.json"

HEADERS = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    "Content-Type": "application/json"
}

# --- Zendesk functions ---

def get_latest_internal_note(ticket_id):
    """
    Fetch the latest internal note (private comment) from ticket audits.
    Returns tuple: (order_name, agent_name, created_at, body)
    """
    url = f"{ZENDESK_API_URL}/tickets/{ticket_id}/audits.json"
    resp = requests.get(url, auth=(EMAIL + "/token", API_TOKEN), verify=False)
    resp.raise_for_status()
    audits = resp.json().get("audits", [])

    latest_note = None
    for audit in audits:
        for event in audit.get("events", []):
            if event.get("type") == "Comment" and not event.get("public", True):
                body = event.get("body", "")
                match = re.search(r"\b[aA]\d+\b", body)
                if match:
                    order_name = match.group(0)
                    created_at = audit.get("created_at", "")
                    author_id = event.get("author_id")
                    agent_name = get_zendesk_user_name(author_id)
                    latest_note = (order_name, agent_name, created_at, body)
    return latest_note

def get_zendesk_user_name(user_id):
    """Fetch Zendesk agent name by ID."""
    url = f"{ZENDESK_API_URL}/users/{user_id}.json"
    resp = requests.get(url, auth=(EMAIL + "/token", API_TOKEN), verify=False)
    if resp.status_code == 200:
        return resp.json().get("user", {}).get("name", "Unknown Agent")
    return "Unknown Agent"

# --- Shopify functions ---

def get_order_id_by_name(order_name):
    """
    Fetch Shopify order ID by order name using GraphQL.
    """
    query = """
    query getOrderByName($name: String!) {
      orders(first: 1, query: $name) {
        edges {
          node {
            id
            name
          }
        }
      }
    }
    """
    variables = {"name": order_name}
    resp = requests.post(SHOPIFY_GRAPHQL_URL, headers=HEADERS, json={"query": query, "variables": variables}, verify=False)
    resp.raise_for_status()
    data = resp.json()
    edges = data.get("data", {}).get("orders", {}).get("edges", [])
    if edges:
        return edges[0]["node"]["id"]
    return None

def append_order_timeline_comment(order_name, message):
    """
    Append a timeline comment to a Shopify order.
    """
    order_id = get_order_id_by_name(order_name)
    if not order_id:
        print(f"❌ No Shopify order found for {order_name}")
        return

    mutation = """
    mutation orderTimelineCommentCreate($input: OrderTimelineCommentCreateInput!) {
      orderTimelineCommentCreate(input: $input) {
        timelineComment {
          id
          message
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    variables = {"input": {"id": order_id, "message": message}}
    resp = requests.post(SHOPIFY_GRAPHQL_URL, headers=HEADERS, json={"query": mutation, "variables": variables}, verify=False)
    resp.raise_for_status()
    result = resp.json()
    errors = result.get("data", {}).get("orderTimelineCommentCreate", {}).get("userErrors", [])
    if errors:
        print(f"❌ Errors creating timeline comment for order {order_name}: {errors}")
    else:
        print(f"✅ Timeline comment added to order {order_name}")

# --- Main sync function ---

def sync_note(ticket_id):
    note = get_latest_internal_note(ticket_id)
    if not note:
        print(f"❌ No internal note with order number found in ticket {ticket_id}")
        return

    order_name, agent_name, created_at, body = note
    # Format timestamp nicely
    timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
    message = f"[Zendesk Internal Note]\nTicket #{ticket_id}\nBy: {agent_name} at {timestamp}\n\n{body}"

    append_order_timeline_comment(order_name, message)

# --- CLI entry point ---

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python script.py sync_note <ticket_id>")
        sys.exit(1)

    action = sys.argv[1]
    ticket_id = sys.argv[2]

    if action == "sync_note":
        sync_note(ticket_id)
    else:
        print(f"Action '{action}' not supported.")
