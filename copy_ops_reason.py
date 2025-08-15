import os
import logging
import requests
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

SUBDOMAIN = os.environ["SUBDOMAIN"]
EMAIL = os.environ["EMAIL"]
API_TOKEN = os.environ["API_TOKEN"]

BASE_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
AUTH = (f"{EMAIL}/token", API_TOKEN)

OPS_ESCALATION_REASON_ID = 20837946693533
VIEW_ID = 27529425733661  # Ops Escalation Reason Empty

# ------------------------
# API Helpers
# ------------------------
def zendesk_get(url):
    resp = requests.get(url, auth=AUTH)
    if resp.status_code != 200:
        logging.error(f"GET {url} failed: {resp.status_code} {resp.text}")
        return None
    return resp.json()

def zendesk_put(url, data):
    resp = requests.put(url, json=data, auth=AUTH)
    if resp.status_code != 200:
        logging.error(f"PUT {url} failed: {resp.status_code} {resp.text}")
        return False
    return True

def get_tickets_from_view(view_id):
    url = f"{BASE_URL}/views/{view_id}/tickets.json"
    tickets = []
    while url:
        data = zendesk_get(url)
        if not data:
            break
        tickets.extend(data.get("tickets", []))
        url = data.get("next_page")
    return tickets

def get_side_conversations(ticket_id):
    url = f"{BASE_URL}/tickets/{ticket_id}/side_conversations.json"
    data = zendesk_get(url)
    return data.get("side_conversations", []) if data else []

def get_ticket_field(ticket, field_id):
    for field in ticket.get("custom_fields", []):
        if field["id"] == field_id:
            return field.get("value")
    return None

def get_ticket(ticket_id):
    url = f"{BASE_URL}/tickets/{ticket_id}.json"
    data = zendesk_get(url)
    return data.get("ticket") if data else None

def set_ticket_field(ticket_id, field_id, value):
    url = f"{BASE_URL}/tickets/{ticket_id}.json"
    payload = {
        "ticket": {
            "custom_fields": [
                {"id": field_id, "value": value}
            ]
        }
    }
    return zendesk_put(url, payload)

def add_internal_note(ticket_id, requester_id, child_ticket_id):
    """Add internal note to parent ticket asking requester to fill Ops Escalation Reason."""
    message = (
        f"@user-{requester_id} ⚠ Please add the Ops Escalation Reason for this ticket. "
        f"This was triggered by child ticket #{child_ticket_id}."
    )
    payload = {
        "ticket": {
            "comment": {
                "body": message,
                "public": False
            }
        }
    }
    return zendesk_put(f"{BASE_URL}/tickets/{ticket_id}.json", payload)

# ------------------------
# Reverse Lookup using external_ids.targetTicketId
# ------------------------
def find_parent_for_child(child_id):
    """Search for a parent ticket whose side conversation external_ids.targetTicketId matches child_id."""
    date_30_days_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    search_url = (
        f"{BASE_URL}/search.json?"
        f"query=type:ticket custom_field_{OPS_ESCALATION_REASON_ID}:* created>{date_30_days_ago}"
    )

    results = zendesk_get(search_url)
    if not results:
        return None

    for t in results.get("results", []):
        side_convos = get_side_conversations(t["id"])
        for sc in side_convos:
            external_ids = sc.get("external_ids", {})
            target_id = external_ids.get("targetTicketId")
            if str(target_id) == str(child_id):
                logging.debug(f"Found parent {t['id']} for child {child_id}")
                return t["id"]

    return None

# ------------------------
# Main Logic
# ------------------------
def main():
    tickets = get_tickets_from_view(VIEW_ID)
    logging.info(f"Found {len(tickets)} tickets in view {VIEW_ID}.")

    for child_ticket in tickets:
        child_id = child_ticket["id"]

        # Find parent ticket via external_ids.targetTicketId
        parent_id = find_parent_for_child(child_id)
        if not parent_id:
            logging.warning(f"⚠ Ticket {child_id} — no parent found via external_ids.targetTicketId.")
            continue

        parent_ticket = get_ticket(parent_id)
        if not parent_ticket:
            logging.debug(f"Skipping ticket {child_id} — failed to fetch parent {parent_id}.")
            continue

        parent_value = get_ticket_field(parent_ticket, OPS_ESCALATION_REASON_ID)
        requester_id = parent_ticket.get("requester_id")

        if not parent_value:
            # Parent missing Ops Escalation Reason → add internal note
            if add_internal_note(parent_id, requester_id, child_id):
                logging.info(f"📝 Added internal note to parent ticket {parent_id} asking requester to add Ops Escalation Reason")
            else:
                logging.error(f"❌ Failed to add internal note to parent ticket {parent_id}")
            continue

        # Copy to child ticket
        if set_ticket_field(child_id, OPS_ESCALATION_REASON_ID, parent_value):
            logging.info(f"✅ Copied Ops Escalation Reason from parent {parent_id} → child {child_id}")
        else:
            logging.error(f"❌ Failed to update ticket {child_id}")

if __name__ == "__main__":
    main()
