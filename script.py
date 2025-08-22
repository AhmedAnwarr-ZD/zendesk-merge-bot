import os
import sys
import re
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ---- Shopify credentials ----
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")

# ---- Zendesk credentials ----
EMAIL = os.getenv("EMAIL")
API_TOKEN = os.getenv("API_TOKEN")

# -----------------------------------
# Shopify helper to update order note
# -----------------------------------
def shopify_update_order_note(order_id, new_note):
    url = f"https://{SHOPIFY_DOMAIN}/admin/api/2023-10/orders/{order_id}.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json",
    }
    payload = {"order": {"id": order_id, "note": new_note}}
    resp = requests.put(url, headers=headers, json=payload)

    if resp.status_code not in (200, 201):
        raise Exception(f"Shopify update failed: {resp.status_code}, {resp.text}")
    print(f"✅ Shopify note updated for order {order_id}")

# -----------------------------------
# Zendesk helper: fetch latest private note
# -----------------------------------
def get_latest_private_note(ticket_id):
    url = f"https://shopaleena.zendesk.com/api/v2/tickets/{ticket_id}/audits.json"
    auth = (f"{EMAIL}/token", API_TOKEN)
    resp = requests.get(url, auth=auth)
    resp.raise_for_status()
    audits = resp.json().get("audits", [])

    # find latest private note
    for audit in reversed(audits):
        for ev in audit.get("events", []):
            if ev.get("type") == "Comment" and ev.get("public") is False:
                return ev.get("body", ""), audit.get("author_id")
    return None, None

# -----------------------------------
# Sync logic: override note in Shopify
# -----------------------------------
def sync_note(ticket_id):
    print(f"Debug: syncing ticket_id={ticket_id}")

    # ✅ fetch only latest private note
    note_text, agent_id = get_latest_private_note(ticket_id)
    if not note_text:
        raise Exception("No private note found.")

    ts_date = datetime.now().strftime("%Y-%m-%d")

    # extract order name like "A273302"
    match = re.search(r"([A-Z0-9]+)", note_text)
    order_name = match.group(1) if match else None

    message_block = f"#{ticket_id} | {agent_id} | {ts_date}\n\n{note_text}"

    print(f"Debug: order_name={order_name}, agent={agent_id}, ts_date={ts_date}")
    print("Debug: message_block:")
    print(message_block)

    if not order_name:
        raise Exception("Could not detect order number in note text.")

    # ✅ Get Shopify order by name
    url = f"https://{SHOPIFY_DOMAIN}/admin/api/2023-10/orders.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    resp = requests.get(url, headers=headers, params={"name": order_name})
    resp.raise_for_status()
    orders = resp.json().get("orders", [])

    if not orders:
        raise Exception(f"No Shopify order found for {order_name}")

    shop_order = orders[0]

    # ✅ override the note with private note
    shopify_update_order_note(shop_order["id"], message_block)


# -----------------------------------
# Entrypoint
# -----------------------------------
if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "sync_note":
        sync_note(int(sys.argv[2]))
    else:
        print("Usage: python script.py sync_note <ticket_id>")
