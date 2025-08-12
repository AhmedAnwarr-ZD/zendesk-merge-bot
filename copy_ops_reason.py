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

OPS_ESCALATION_FIELD_ID = 20837946693533  # real field ID

# ------------------------
# API Helpers
# ------------------------
def zendesk_get(path):
    url = f"{BASE_URL}{path}"
    resp = requests.get(url, auth=AUTH)
    if resp.status_code != 200:
        logging.error(f"GET {path} failed ({resp.status_code}): {resp.text}")
        return None
    return resp.json()

def zendesk_put(path, payload):
    url = f"{BASE_URL}{path}"
    resp = requests.put(url, json=payload, auth=AUTH)
    if resp.status_code != 200:
        logging.error(f"PUT {path} failed ({resp.status_code}): {resp.text}")
        return False
    return True

def search_unsolved_side_conversations():
    """Find all unsolved tickets with side conversations."""
    query = 'type:ticket status<solved'
    tickets = []
    page = f"/search.json?query={query}"
    while page:
        data = zendesk_get(page)
        if not data:
            break
        for t in data.get("results", []):
            if t.get("status") in ["new", "open", "pending"]:
                tickets.append(t)
        page = data.get("next_page")
        if page:
            page = page.replace(BASE_URL, "")
    return tickets

def get_ops_reason_from_ticket(ticket_id):
    """Return Ops Escalation Reason from ticket's custom fields."""
    data = zendesk_get(f"/tickets/{ticket_id}.json")
    if not data:
        return None
    for f in data["ticket"].get("custom_fields", []):
        if f["id"] == OPS_ESCALATION_FIELD_ID and f["value"]:
            return f["value"]
    return None

def get_side_conversations(ticket_id):
    """Return all side conversations for a ticket."""
    data = zendesk_get(f"/tickets/{ticket_id}/side_conversations.json")
    if not data:
        return []
    return data.get("side_conversations", [])

def get_side_conversation_messages(conv_id):
    """Return all messages from a side conversation."""
    data = zendesk_get(f"/side_conversations/{conv_id}/messages.json")
    if not data:
        return []
    return data.get("events", [])

def update_side_conversation(conv_id, message):
    """Add a message to the side conversation."""
    payload = {
        "event": {
            "type": "message",
            "body": message
        }
    }
    return zendesk_put(f"/side_conversations/{conv_id}/messages.json", payload)

# ------------------------
# Main Logic
# ------------------------
def main():
    tickets = search_unsolved_side_conversations()
    logging.info(f"Found {len(tickets)} unsolved tickets.")

    for t in tickets:
        parent_id = t.get("via", {}).get("followup_source_id")
        if not parent_id:
            logging.debug(f"Skipping ticket {t['id']} — no parent ticket.")
            continue

        ops_reason = get_ops_reason_from_ticket(parent_id)
        if not ops_reason:
            logging.debug(f"Parent ticket {parent_id} has no Ops Escalation Reason.")
            continue

        side_convs = get_side_conversations(t["id"])
        if not side_convs:
            logging.debug(f"No side conversations found for ticket {t['id']}.")
            continue

        for sc in side_convs:
            conv_id = sc["id"]

            # Fetch all messages in the conversation
            messages = get_side_conversation_messages(conv_id)
            body_texts = [m.get("body", "").strip().lower() for m in messages if m.get("body")]

            if any("ops escalation reason" in msg for msg in body_texts):
                logging.debug(f"Side conversation {conv_id} already has Ops Escalation Reason.")
                continue

            # Append the Ops Escalation Reason
            message_body = f"Ops Escalation Reason: {ops_reason}"
            if update_side_conversation(conv_id, message_body):
                logging.info(f"✅ Added Ops Escalation Reason to side conversation {conv_id} for ticket {t['id']}.")

if __name__ == "__main__":
    main()
