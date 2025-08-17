import os
import sys
import re
import json
from datetime import datetime
import requests

# ========== ENV ==========
# (Match your existing GitHub secrets)
EMAIL = os.getenv("EMAIL")                   # Zendesk email (agent) used with token auth
API_TOKEN = os.getenv("API_TOKEN")           # Zendesk API token
SUBDOMAIN = os.getenv("SUBDOMAIN")           # Zendesk subdomain (e.g., "acme" for acme.zendesk.com)

SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")   # Shopify Admin API access token
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN") # Shopify subdomain (e.g., "yourstore" for yourstore.myshopify.com)

API_VERSION = "2025-07"

ZENDESK_API_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
SHOPIFY_GRAPHQL_URL = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/{API_VERSION}/graphql.json"

SHOPIFY_HEADERS = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    "Content-Type": "application/json",
}

# ========== HTTP HELPERS ==========

def zendesk_get(url):
    """GET to Zendesk with helpful error output."""
    resp = requests.get(url, auth=(f"{EMAIL}/token", API_TOKEN))
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"❌ Zendesk request failed: {e}")
        try:
            print("👉 Response JSON:", resp.json())
        except Exception:
            print("👉 Raw response:", resp.text)
        raise
    return resp.json()

def shopify_post(query, variables=None):
    """POST GraphQL to Shopify with helpful error output."""
    payload = {"query": query}
    if variables is not None:
        payload["variables"] = variables
    resp = requests.post(SHOPIFY_GRAPHQL_URL, headers=SHOPIFY_HEADERS, json=payload)
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"❌ Shopify request failed: {e}")
        try:
            print("👉 Response JSON:", resp.json())
        except Exception:
            print("👉 Raw response:", resp.text)
        raise
    data = resp.json()
    if "errors" in data and data["errors"]:
        print("❌ Shopify GraphQL errors:", data["errors"])
        raise RuntimeError("Shopify GraphQL returned errors")
    return data

# ========== ZENDESK ==========

ORDER_NAME_PATTERNS = [
    re.compile(r"\b[Aa]\d{3,}\b"),      # A12345 / a1234567 (your format)
    re.compile(r"#\d{3,}\b"),           # #12345  (Shopify default style, just in case)
]

def extract_order_name(text):
    if not text:
        return None
    for pat in ORDER_NAME_PATTERNS:
        m = pat.search(text)
        if m:
            # Normalize: uppercase leading letter if present (A12345), else keep as-is
            val = m.group(0)
            if val.startswith(("a", "A")):
                return "A" + val[1:]
            return val
    return None

def get_latest_internal_note(ticket_id):
    """
    Returns dict: {
      'order_name': 'A266626' (or None),
      'body': 'note body',
      'author_id': 1234567890,
      'author_name': 'Agent Name' (best effort),
      'created_at': '2025-08-17T12:34:56Z'
    }
    """
    audits_url = f"{ZENDESK_API_URL}/tickets/{ticket_id}/audits.json"
    audits = zendesk_get(audits_url).get("audits", [])

    latest = None
    for audit in audits:
        created_at = audit.get("created_at")
        for event in audit.get("events", []):
            # Internal note = Comment with public == False
            if event.get("type") == "Comment" and not event.get("public", True):
                body = event.get("body", "") or ""
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

    # Try to fetch agent name
    agent_name = "Unknown Agent"
    if latest.get("author_id"):
        try:
            u = zendesk_get(f"{ZENDESK_API_URL}/users/{latest['author_id']}.json")
            agent_name = u.get("user", {}).get("name", agent_name)
        except Exception:
            pass
    latest["author_name"] = agent_name
    return latest

# ========== SHOPIFY (GRAPHQL) ==========

def shopify_find_order(order_name):
    """
    Find order by name using GraphQL search.
    Returns dict: {'id': <gid>, 'name': <name>, 'note': <note or ''>, 'notes_log': <metafield dict or None>}
    """
    query = """
    query($q: String!) {
      orders(first: 1, query: $q) {
        edges {
          node {
            id
            name
            note
            metafield(namespace: "zendesk", key: "notes_log") {
              id
              type
              value
            }
          }
        }
      }
    }
    """
    # Important: include the filter key in the query string
    variables = {"q": f"name:{order_name}"}
    data = shopify_post(query, variables)
    edges = data.get("data", {}).get("orders", {}).get("edges", [])
    if not edges:
        return None
    node = edges[0]["node"]
    return {
        "id": node["id"],
        "name": node.get("name"),
        "note": node.get("note") or "",
        "notes_log": node.get("metafield"),
    }

def shopify_update_order_note(order_gid, old_note, message_block):
    """
    Append to order.note (staff-visible). Uses orderUpdate.
    """
    combined = f"{old_note}\n---\n{message_block}".strip() if old_note else message_block
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
    print("✅ Order note updated")

def shopify_append_notes_log_metafield(order_gid, existing_mf, entry):
    """
    Append the entry to a single 'notes_log' metafield (type: json).
    Creates it if missing.
    """
    # Prepare new list
    entries = []
    if existing_mf and existing_mf.get("value") and existing_mf.get("type") == "json":
        try:
            entries = json.loads(existing_mf["value"])
            if not isinstance(entries, list):
                entries = []
        except Exception:
            entries = []
    entries.append(entry)

    mutation = """
    mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
      metafieldsSet(metafields: $metafields) {
        metafields { id key namespace type value }
        userErrors { field message }
      }
    }
    """
    variables = {
        "metafields": [{
            "ownerId": order_gid,
            "namespace": "zendesk",
            "key": "notes_log",
            "type": "json",
            "value": json.dumps(entries),
        }]
    }
    data = shopify_post(mutation, variables)
    errs = data.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
    if errs:
        raise RuntimeError(f"Shopify metafieldsSet errors: {errs}")
    print("✅ Metafield (zendesk.notes_log) updated")

# ========== MAIN FLOW ==========

def sync_note(ticket_id: str):
    note = get_latest_internal_note(ticket_id)
    if not note:
        print(f"❌ No internal note found in Zendesk ticket {ticket_id}")
        return

    order_name = note.get("order_name")
    if not order_name:
        print(f"❌ Could not detect a Shopify order name in the latest internal note of ticket {ticket_id}")
        return

    shop_order = shopify_find_order(order_name)
    if not shop_order:
        print(f"❌ Shopify order not found for name {order_name}")
        return

    # Pretty timestamp
    created_at = note.get("created_at") or ""
    try:
        ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S %Z") if ts.tzinfo else ts.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        ts_str = created_at

    agent = note.get("author_name", "Unknown Agent")
    body = note.get("body", "").strip()

    # Block to append to Notes
    message_block = f"[Zendesk Internal Note]\nTicket #{ticket_id}\nBy: {agent} at {ts_str}\n\n{body}"

    # Append to order.note
    shopify_update_order_note(shop_order["id"], shop_order["note"], message_block)

    # Append to metafield JSON log
    entry = {
        "ticket_id": str(ticket_id),
        "author": agent,
        "note": body,
        "created_at": created_at,
    }
    shopify_append_notes_log_metafield(shop_order["id"], shop_order["notes_log"], entry)

    print(f"✅ Synced Zendesk ticket #{ticket_id} → Shopify order {shop_order['name']} (Notes + Metafield)")

# ========== CLI ==========

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
