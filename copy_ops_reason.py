import os
import logging
import requests

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
    if not data:
        return []
    return data.get("side_conversations", [])

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

# ------------------------
# Parent Finder
# ------------------------
def find_parent_ticket_id(ticket):
    # 1. Check side conversations
    side_convos = get_side_conversations(ticket["id"])
    for sc in side_convos:
        if sc.get("ticket_id") and sc["ticket_id"] != ticket["id"]:
            return sc["ticket_id"]

    # 2. Check follow-up source
    if ticket.get("via", {}).get("followup_source_id"):
        return ticket["via"]["followup_source_id"]

    # 3. Check problem/incident relationship
    if ticket.get("problem_id"):
        return ticket["problem_id"]

    # 4. Check custom field (if you have one that stores parent ticket ID)
    PARENT_TICKET_FIELD_ID = None  # put actual ID if exists
    if PARENT_TICKET_FIELD_ID:
        for field in ticket.get("custom_fields", []):
            if field["id"] == PARENT_TICKET_FIELD_ID and field["value"]:
                return field["value"]

    # No parent found
    return None

# ------------------------
# Main Logic
# ------------------------
def main():
    tickets = get_tickets_from_view(VIEW_ID)
    logging.info(f"Found {len(tickets)} tickets in view {VIEW_ID}.")

    for child_ticket in tickets:
        child_id = child_ticket["id"]

        # Try to find parent ticket
        parent_id = find_parent_ticket_id(child_ticket)

        if not parent_id:
            logging.warning(f"⚠ Ticket {child_id} — no parent found in side convos, follow-ups, or problem links.")
            # Instead of skipping, we still try nothing here, or we could add logic to fetch from other sources
            continue

        parent_ticket = get_ticket(parent_id)
        if not parent_ticket:
            logging.debug(f"Skipping ticket {child_id} — failed to fetch parent {parent_id}.")
            continue

        parent_value = get_ticket_field(parent_ticket, OPS_ESCALATION_REASON_ID)
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
