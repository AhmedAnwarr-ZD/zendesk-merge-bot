import os
import sys
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ---- Shopify credentials ----
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")

# ---- Zendesk credentials ----
SUBDOMAIN = os.getenv("SUBDOMAIN")
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
# Zendesk helper to fetch ticket info
# -----------------------------------
def get_ticket(ticket_id):
    url = f"https://{SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
    auth = (f"{EMAIL}/token", API_TOKEN)
    resp = requests.get(url, auth=auth)
    resp.raise_for_status()
    return resp.json()["ticket"]

# -----------------------------------
# Sync logic: override note in Shopify
# -----------------------------------
def sync_note(ticket_id):
    print(f"Debug: syncing ticket_id={ticket_id}")

    ticket = get_ticket(ticket_id)
    order_name = ticket.get("external_id") or ticket.get("subject") or "Unknown"
    agent = ticket.get("assignee_id", "Unknown")
    ts_date = datetime.now().strftime("%Y-%m-%d")

    message_block = f"#{ticket_id} | {agent} | {ts_date}\n\n{ticket['description']}"

    print(f"Debug: order_name={order_name}, agent={agent}, ts_date={ts_date}")
    print("Debug: message_block:")
    print(message_block)

    # Get Shopify order by name
    url = f"https://{SHOPIFY_DOMAIN}/admin/api/2023-10/orders.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    resp = requests.get(url, headers=headers, params={"name": order_name})
    resp.raise_for_status()
    orders = resp.json().get("orders", [])

    if not orders:
        raise Exception(f"No Shopify order found for {order_name}")

    shop_order = orders[0]

    # ✅ Now override the note with our block
    shopify_update_order_note(shop_order["id"], message_block)


# -----------------------------------
# Entrypoint
# -----------------------------------
if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "sync_note":
        sync_note(int(sys.argv[2]))
    else:
        print("Usage: python script.py sync_note <ticket_id>")
