import os
import logging
import requests

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# ------------------------
# Zendesk API Setup
# ------------------------
SUBDOMAIN = os.environ["SUBDOMAIN"]
EMAIL = os.environ["EMAIL"]
API_TOKEN = os.environ["API_TOKEN"]

BASE_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
AUTH = (f"{EMAIL}/token", API_TOKEN)

# Custom field ID for Ops Escalation Reason
OPS_ESCALATION_REASON_ID = 20837946693533

# ------------------------
# API Functions
# ------------------------
def zendesk_get(url):
    """Generic GET request to Zendesk API"""
    resp = requests.get(url, auth=AUTH)
    if resp.status_code != 200:
        logging.error(f"GET {url} failed: {resp.status_code} {resp.text}")
        return None
    return resp.json()

def zendesk_put(url, data):
    """Generic PUT request to Zendesk API"""
    resp = requests.put(url, json=data, auth=AUTH)
    if resp.status_code != 200:
        logging.error(f"PUT {url} failed: {resp.status_code} {resp.text}")
        return False
    return True

def search_side_conversation_tickets():
    """Find all unsolved side conversation tickets"""
    query = 'type:ticket status<solved'
    url = f"{BASE_URL}/search.json?query={query}"
    results = []
    while url:
        data = zendesk_get(url)
        if not data:
            break
        for t in data.get("results", []):
            if t.get("via", {}).get("channel") == "side_conversation":
                results.append(t)
        url = data.get("next_page")
    return results

def get_side_conversations(ticket_id):
    """Get side conversations for a ticket"""
    url = f"{BASE_URL}/tickets/{ticket_id}/side_conversations.json"
    data = zendesk_get(url)
    if not data:
        return []
    return data.get("side_conversations", [])

def get_ticket_field(ticket_id, field_id):
    """Fetch specific custom field value from a ticket"""
    url = f"{BASE_URL}/tickets/{ticket_id}.json"
    data = zendesk_get(url)
    if not data:
        return None
    for field in data["ticket"].get("custom_fields", []):
        if field["id"] == field_id:
            return field.get("value")
    return None

def set_ticket_field(ticket_id, field_id, value):
    """Update specific custom field value on a ticket"""
    url = f"{BASE_URL}/tickets/{ticket_id}.json"
    payload = {
        "ticket": {
            "custom_fields": [
                {"id": field_id, "value": value}
            ]
        }
    }
    return zendesk_put(url, payload)

# ------------------------
# Main logic
# ------------------------
def main():
    tickets = search_side_conversation_tickets()
    logging.info(f"Found {len(tickets)} unsolved side conversation tickets.")

    for child_ticket in tickets:
        child_id = child_ticket["id"]

        # Check current Ops Escalation Reason in child
        child_value = get_ticket_field(child_id, OPS_ESCALATION_REASON_ID)
        if child_value:
            logging.debug(f"Skipping ticket {child_id} — already has Ops Escalation Reason.")
            continue

        # Try to find the parent via side conversation API
        side_convos = get_side_conversations(child_id)
        parent_id = None
        for sc in side_convos:
            if sc.get("ticket_id") and sc["ticket_id"] != child_id:
                parent_id = sc["ticket_id"]
                break

        if not parent_id:
            logging.debug(f"Skipping ticket {child_id} — could not find parent from side conversation.")
            continue

        # Get Ops Escalation Reason from parent
        parent_value = get_ticket_field(parent_id, OPS_ESCALATION_REASON_ID)
        if not parent_value:
            logging.debug(f"Parent ticket {parent_id} has no Ops Escalation Reason.")
            continue

        # Copy to child ticket
        if set_ticket_field(child_id, OPS_ESCALATION_REASON_ID, parent_value):
            logging.info(f"✅ Copied Ops Escalation Reason from parent {parent_id} → child {child_id}")
        else:
            logging.error(f"❌ Failed to update ticket {child_id}")

if __name__ == "__main__":
    main()
