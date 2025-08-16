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

def get_zendesk_ticket(ticket_id):
    url = f"{ZENDESK_API_URL}/tickets/{ticket_id}.json"
    resp = requests.get(url, auth=(EMAIL + "/token", API_TOKEN), verify=False)
    resp.raise_for_status()
    return resp.json()["ticket"]

def get_order_name_from_internal_notes(ticket):
    """
    Extract Shopify order name from INTERNAL notes only.
    Matches formats: A123456, a123456789 etc.
    """
    internal_notes = ticket.get("audit", {}).get("events", [])
    for note in internal_notes:
        if note.get("type") == "Comment" and note.get("public") is False:
            body = note.get("body", "")
            match = re.search(r"\b[aA]\d+\b", body)
            if match:
                return match.group(0)
    return None

def find_order_id_by_name(order_name):
    """
    Shopify API cannot GET by 'name', so fetch orders and match manually.
    """
    url = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2024-01/orders.json?status=any&limit=250"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Typ
