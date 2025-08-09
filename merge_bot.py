import requests
from collections import defaultdict
import os
from datetime import datetime

# Load credentials from GitHub Actions secrets
SUBDOMAIN = os.environ["SUBDOMAIN"]
EMAIL = os.environ["EMAIL"]
API_TOKEN = os.environ["API_TOKEN"]

BASE_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
AUTH = (f"{EMAIL}/token", API_TOKEN)

def log(msg):
    """Print logs with a timestamp."""
    print(f"[{datetime.utcnow().isoformat()} UTC] {msg}")

def get_all_side_convo_tickets():
    tickets = []
    url = f"{BASE_URL}/search.json?query=type:ticket via:side_conversation"
    while url:
        resp = requests.get(url, auth=AUTH)
        resp.raise_for_status()
        data = resp.json()
        tickets.extend(data["results"])
        url = data.get("next_page")
    log(f"Found {len(tickets)} side conversation tickets.")
    return tickets

def reopen_ticket(ticket_id):
    log(f"Reopening solved ticket {ticket_id}")
    payload = {"ticket": {"status": "open"}}
    requests.put(f"{BASE_URL}/tickets/{ticket_id}.json", json=payload, auth=AUTH).raise_for_status()

def solve_ticket(ticket_id):
    log(f"Solving ticket {ticket_id}")
    payload = {"ticket": {"status": "solved"}}
    requests.put(f"{BASE_URL}/tickets/{ticket_id}.json", json=payload, auth=AUTH).raise_for_status()

def add_private_note_to_ticket(ticket_id, note):
    log(f"Adding private note to ticket {ticket_id}")
    payload = {
        "ticket": {
            "comment": {
                "body": note,
                "public": False
            }
        }
    }
    requests.put(f"{BASE_URL}/tickets/{ticket_id}.json", json=payload, auth=AUTH).raise_for_status()

def merge_child_tickets():
    tickets = get_all_side_convo_tickets()

    # Group by subject
    grouped = defaultdict(list)
    for t in tickets:
        grouped[t["subject"]].append(t)

    for subject, ticket_list in grouped.items():
        if len(ticket_list) < 2:
            continue  # no duplicates to merge

        ticket_list.sort(key=lambda x: x["created_at"])
        main_ticket = ticket_list[0]
        duplicates = ticket_list[1:]

        log(f"Merging {len(duplicates)} child tickets into main ticket {main_ticket['id']} for subject: {subject}")

        for dup in duplicates:
            if dup["status"] == "solved":
                reopen_ticket(dup["id"])

            add_private_note_to_ticket(main_ticket["id"], f"Merged from ticket {dup['id']}:\n\n{dup['description']}")

            solve_ticket(dup["id"])

if __name__ == "__main__":
    merge_child_tickets()
