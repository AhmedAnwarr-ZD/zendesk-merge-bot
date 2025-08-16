import os
import sys
import requests
import re
from dotenv import load_dotenv

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

def get_zendesk_ticket(ticket_id):
    url = f"{ZENDESK_API_URL}/tickets/{ticket_id}.json"
    resp = requests.get(url, auth=(EMAIL + "/token", API_TOKEN), verify=False)
    resp.raise_for_status()
    return resp.json()["ticket"]

def get_order_name_from_internal_notes(ticket_id):
    """
    Fetch ticket audits and extract Shopify order name from internal notes only.
    Matches patterns like A123456 or a123456789.
    """
    url = f"{ZENDESK_API_URL}/tickets/{ticket_id}/audits.json"
    resp = requests.get(url, auth=(EMAIL + "/token", API_TOKEN), verify=False)
    resp.raise_for_status()
    audits = resp.json().get("audits", [])

    for audit in audits:
        for event in audit.get("events", []):
            if event.get("type") == "Comment" and not event.get("public", True):
                body = event.get("body", "")
                match = re.search(r"\b[aA]\d+\b", body)
                if match:
                    return match.group(0)
    return None

# --- Shopify GraphQL functions ---

def get_order_id_by_name(order_name):
    """
    Fetch Shopify order ID by name using GraphQL.
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

def append_order_note(order_name, note_text):
    """
    Append a note to a Shopify order using GraphQL mutation.
    """
    order_id = get_order_id_by_name(order_name)
    if not order_id:
        print(f"No Shopify order found for {order_name}")
        return

    mutation = """
    mutation updateOrderNote($id: ID!, $note: String!) {
      orderUpdate(input: {id: $id, note: $note}) {
        order {
          id
          note
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    variables = {"id": order_id, "note": note_text}
    resp = requests.post(SHOPIFY_GRAPHQL_URL, headers=HEADERS, json={"query": mutation, "variables": variables}, verify=False)
    resp.raise_for_status()
    result = resp.json()
    errors = result.get("data", {}).get("orderUpdate", {}).get("userErrors", [])
    if errors:
        print(f"Errors updating order {order_name}: {errors}")
    else:
        print(f"Order {order_name} updated successfully.")

# --- Main sync function ---

def sync_note(ticket_id):
    ticket = get_zendesk_ticket(ticket_id)
    order_name = get_order_name_from_internal_notes(ticket_id)

    if not order_name:
        print(f"No Shopify order name found in internal notes of ticket {ticket_id}")
        return

    comment_text = ticket.get("description", "")
    final_note = f"Zendesk Ticket #{ticket_id}: {comment_text}"
    append_order_note(order_name, final_note)
    print(f"Synced ticket #{ticket_id} to Shopify order {order_name}")

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
