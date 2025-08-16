import os
import sys
import requests
from dotenv import load_dotenv
import urllib3

# Skip SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

EMAIL = os.getenv("EMAIL")
API_TOKEN = os.getenv("API_TOKEN")
SUBDOMAIN = os.getenv("SUBDOMAIN")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")

ZENDESK_API_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"

def get_zendesk_ticket(ticket_id):
    url = f"{ZENDESK_API_URL}/tickets/{ticket_id}.json"
    resp = requests.get(url, auth=(EMAIL + "/token", API_TOKEN), verify=False)
    resp.raise_for_status()
    return resp.json()["ticket"]

def get_order_name_from_internal_notes(ticket):
    # Search all internal notes (Zendesk comments with 'public': False)
    url = f"{ZENDESK_API_URL}/tickets/{ticket['id']}/comments.json"
    resp = requests.get(url, auth=(EMAIL + "/token", API_TOKEN), verify=False)
    resp.raise_for_status()
    comments = resp.json().get("comments", [])
    
    import re
    for c in comments:
        if not c.get("public", True):
            match = re.search(r"\bA\d+\b", c.get("body", ""), re.IGNORECASE)
            if match:
                return match.group(0).upper()  # Normalize to uppercase
    return None

def append_order_note(order_name, note_text):
    search_url = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2024-01/orders.json?name={order_name}"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json"
    }
    
    try:
        resp = requests.get(search_url, headers=headers, verify=False)
        resp.raise_for_status()
        orders = resp.json().get("orders", [])
        if not orders:
            print(f"No Shopify order found with name {order_name}")
            return
        order_id = orders[0]["id"]

        update_url = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2024-01/orders/{order_id}.json"
        payload = {"order": {"id": order_id, "note": note_text}}
        resp = requests.put(update_url, headers=headers, json=payload, verify=False)
        resp.raise_for_status()
        print(f"Synced note to Shopify order {order_name} (ID: {order_id})")
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

def sync_note(ticket_id):
    ticket = get_zendesk_ticket(ticket_id)
    order_name = get_order_name_from_internal_notes(ticket)
    if not order_name:
        print(f"No Shopify order name found in internal notes of ticket {ticket_id}")
        return
    
    comment_text = ticket.get("description", "")
    final_note = f"Zendesk Ticket #{ticket_id}: {comment_text}"
    append_order_note(order_name, final_note)

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
