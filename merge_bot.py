import requests
from collections import defaultdict
import os
from datetime import datetime, timedelta
import sys

# Load credentials from environment variables
SUBDOMAIN = os.environ.get("SUBDOMAIN", "").strip()
EMAIL = os.environ.get("EMAIL", "").strip()
API_TOKEN = os.environ.get("API_TOKEN", "").strip()

def log(msg):
    """Print logs with a timestamp."""
    print(f"[{datetime.utcnow().isoformat()} UTC] {msg}")

# Validate environment variables
missing = []
if not SUBDOMAIN:
    missing.append("SUBDOMAIN")
if not EMAIL:
    missing.append("EMAIL")
if not API_TOKEN:
    missing.append("API_TOKEN")

log(f"🔍 Debug: SUBDOMAIN='{SUBDOMAIN}'")
log(f"🔍 Debug: EMAIL='{EMAIL}'")
log(f"🔍 Debug: API_TOKEN length={len(API_TOKEN)}")

if missing:
    log(f"❌ Missing required environment variables: {', '.join(missing)}")
    sys.exit(1)

BASE_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
AUTH = (f"{EMAIL}/token", API_TOKEN)

log(f"✅ Using BASE_URL: {BASE_URL}")

def get_all_side_convo_tickets():
    tickets = []

    # Yesterday's date in YYYY-MM-DD format
    yesterday = (datetime.utcnow().date() - timedelta(days=1)).isoformat()

    url = f"{BASE_URL}/search.json?query=type:ticket created:{yesterday}"

    while url:
        resp = requests.get(url, auth=AUTH)
        if resp.status_code != 200:
            log(f"❌ API error {resp.status_code}: {resp.text}")
            resp.raise_for_status()

        data = resp.json()

        side_convo_tickets = [
            t for t in data.get("results", [])
            if t.get("via", {}).get("channel") == "side_conversation"
        ]
        tickets.extend(side_convo_tickets)

        url = data.get("next_page")
        log(f"Fetched {len(side_convo_tickets)} side convo tickets for {yesterday} (Total so far: {len(tickets)})")

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

    # Group tickets by subject
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
