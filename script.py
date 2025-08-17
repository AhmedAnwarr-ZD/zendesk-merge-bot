import os
import sys
import requests
import json
from datetime import datetime

# === Config ===
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")       # e.g. "yourstore.myshopify.com"
SHOPIFY_TOKEN = os.getenv("SHOPIFY_ADMIN_TOKEN")   # Admin API access token
API_VERSION = "2025-07"

headers = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
    "Content-Type": "application/json"
}

def get_order(order_id):
    url = f"https://{SHOPIFY_DOMAIN}/admin/api/{API_VERSION}/orders/{order_id}.json"
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json()["order"]

def update_order_note(order_id, new_comment):
    order = get_order(order_id)
    old_note = order.get("note") or ""

    # Append Zendesk note at the end with divider
    updated_note = f"{old_note}\n---\n{new_comment}" if old_note else new_comment

    url = f"https://{SHOPIFY_DOMAIN}/admin/api/{API_VERSION}/orders/{order_id}.json"
    payload = {
        "order": {
            "id": order_id,
            "note": updated_note
        }
    }
    r = requests.put(url, headers=headers, json=payload)
    r.raise_for_status()
    print(f"✅ Order note updated for {order['name']}")

def add_order_metafield(order_id, ticket_id, author, note):
    # Save structured note in metafields
    namespace = "zendesk"
    key = f"ticket_{ticket_id}"
    timestamp = datetime.utcnow().isoformat()

    url = f"https://{SHOPIFY_DOMAIN}/admin/api/{API_VERSION}/orders/{order_id}/metafields.json"
    payload = {
        "metafield": {
            "namespace": namespace,
            "key": key,
            "type": "json",
            "value": json.dumps({
                "ticket_id": ticket_id,
                "author": author,
                "note": note,
                "created_at": timestamp
            })
        }
    }
    r = requests.post(url, headers=headers, json=payload)

    # If key exists → update instead of creating
    if r.status_code == 422:
        metafields_url = f"https://{SHOPIFY_DOMAIN}/admin/api/{API_VERSION}/orders/{order_id}/metafields.json"
        existing = requests.get(metafields_url, headers=headers).json()["metafields"]
        mf = next((m for m in existing if m["key"] == key and m["namespace"] == namespace), None)
        if mf:
            update_url = f"https://{SHOPIFY_DOMAIN}/admin/api/{API_VERSION}/metafields/{mf['id']}.json"
            r = requests.put(update_url, headers=headers, json={"metafield": {
                "id": mf["id"],
                "type": "json",
                "value": json.dumps({
                    "ticket_id": ticket_id,
                    "author": author,
                    "note": note,
                    "created_at": timestamp
                })
            }})
    r.raise_for_status()
    print(f"✅ Metafield saved for order {order_id} (ticket {ticket_id})")

def sync_note(order_id, ticket_id, author, note):
    formatted_comment = f"[Zendesk Ticket #{ticket_id}] ({author}) {note}"

    # 1. Append to Order Note
    update_order_note(order_id, formatted_comment)

    # 2. Save to Metafields
    add_order_metafield(order_id, ticket_id, author, note)


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python script.py <order_id> <ticket_id> <author> <note>")
        sys.exit(1)

    order_id = sys.argv[1]
    ticket_id = sys.argv[2]
    author = sys.argv[3]
    note = " ".join(sys.argv[4:])

    sync_note(order_id, ticket_id, author, note)
