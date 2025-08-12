import os
import logging
import requests

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# ------------------------
# Zendesk API Setup
# ------------------------
SUBDOMAIN = os.environ["SUBDOMAIN"]
EMAIL = os.environ["EMAIL"]
API_TOKEN = os.environ["API_TOKEN"]

BASE_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
AUTH = (f"{EMAIL}/token", API_TOKEN)

# ------------------------
# Config
# ------------------------
OPS_ESCALATION_FIELD_ID = 20837946693533  # Replace with your real custom field ID

# ------------------------
# API Helpers
# ------------------------
def get_ticket(ticket_id):
    """Get full ticket details"""
    url = f"{BASE_URL}/tickets/{ticket_id}.json"
    resp = requests.get(url, auth=AUTH)
    resp.raise_for_status()
    return resp.json()["ticket"]

def get_side_conversations(ticket_id):
    """Get all side conversations for a ticket"""
    url = f"{BASE_URL}/tickets/{ticket_id}/side_conversations.json"
    resp = requests.get(url, auth=AUTH)
    resp.raise_for_status()
    return resp.json().get("side_conversations", [])

def reply_to_side_conversation(ticket_id, conversation_id, message):
    """Reply to a side conversation"""
    url = f"{BASE_URL}/tickets/{ticket_id}/side_conversations/{conversation_id}/messages.json"
    payload = {"message": {"body": message}}
    resp = requests.post(url, json=payload, auth=AUTH)
    resp.raise_for_status()
    return resp.json()

def get_custom_field(ticket, field_id):
    """Extract a custom field value by ID"""
    for field in ticket.get("custom_fields", []):
        if field["id"] == field_id:
            return field.get("value")
    return None

def side_conversation_contains(conversation, text):
    """Check if a side conversation already contains the given text"""
    messages = conversation.get("messages", [])
    return any(text.lower() in (msg.get("body") or "").lower() for msg in messages)

# ------------------------
# Main Logic
# ------------------------
def main():
    # Search for unsolved tickets that have side conversations
    query = 'type:ticket status<solved has:side_conversations'
    search_url = f"{BASE_URL}/search.json?query={query}"
    logging.info(f"Searching: {query}")

    resp = requests.get(search_url, auth=AUTH)
    resp.raise_for_status()
    tickets = resp.json().get("results", [])

    logging.info(f"Found {len(tickets)} tickets with side conversations.")

    for ticket in tickets:
        ticket_id = ticket["id"]
        full_ticket = get_ticket(ticket_id)

        # Get parent ticket ID if available
        parent_id = full_ticket.get("via", {}).get("source", {}).get("from", {}).get("id")
        if not parent_id:
            logging.debug(f"Ticket {ticket_id} has no parent ticket.")
            continue

        parent_ticket = get_ticket(parent_id)
        escalation_reason = get_custom_field(parent_ticket, OPS_ESCALATION_FIELD_ID)

        if not escalation_reason:
            logging.debug(f"Parent ticket {parent_id} has no Ops Escalation Reason.")
            continue

        # Get side conversations and only update if empty
        side_convos = get_side_conversations(ticket_id)
        for convo in side_convos:
            convo_id = convo["id"]

            if side_conversation_contains(convo, "Ops Escalation Reason"):
                logging.debug(f"Side conversation {convo_id} already contains escalation reason. Skipping.")
                continue

            logging.info(f"Adding Ops Escalation Reason to side conversation {convo_id} for ticket {ticket_id}")
            reply_to_side_conversation(ticket_id, convo_id, f"Ops Escalation Reason: {escalation_reason}")

if __name__ == "__main__":
    main()
