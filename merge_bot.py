import requests
from collections import defaultdict
import os

# Load credentials from GitHub Actions secrets
SUBDOMAIN = os.environ["SUBDOMAIN"]
EMAIL = os.environ["EMAIL"]
API_TOKEN = os.environ["API_TOKEN"]

BASE_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
AUTH = (f"{EMAIL}/token", API_TOKEN)

def ticket_url(ticket_id):
    return f"https://{SUBDOMAIN}.zendesk.com/agent/tickets/{ticket_id}"

def search_tickets(query):
    url = f"{BASE_URL}/search.json?query={query}"
    response = requests.get(url, auth=AUTH)
    response.raise_for_status()
    return response.json()["results"]

def merge_tickets(source_id, target_id):
    url = f"{BASE_URL}/tickets/{target_id}/merge.json"
    data = {"ids": [source_id]}
    response = requests.post(url, json=data, auth=AUTH)
    response.raise_for_status()
    return response.status_code == 200

def main():
    # Search for tickets within last 24 hours, status less than solved
    query = 'type:ticket status<solved created>24hours'
    tickets = search_tickets(query)

    # Group by requester, subject, and channel
    tickets_by_group = defaultdict(list)
    for t in tickets:
        key = (t["requester_id"], t["subject"].strip().lower(), t["via"]["channel"])
        tickets_by_group[key].append(t)

    for (requester_id, subject, channel), t_list in tickets_by_group.items():
        if len(t_list) > 1:
            # Sort by creation date so oldest is target
            t_list.sort(key=lambda x: x["created_at"])
            target_ticket = t_list[0]

            print(f"\nRequester: {requester_id} | Subject: '{subject}' | Channel: {channel}")
            print(f"  Target Ticket: {target_ticket['id']} ({ticket_url(target_ticket['id'])}) | Channel: {target_ticket['via']['channel']}")

            for ticket in t_list[1:]:
                merged = merge_tickets(ticket["id"], target_ticket["id"])
                if merged:
                    print(f"    ✅ Merged Ticket {ticket['id']} ({ticket_url(ticket['id'])}) | Channel: {ticket['via']['channel']} → {target_ticket['id']} ({ticket_url(target_ticket['id'])})")
                else:
                    print(f"    ❌ Failed to merge Ticket {ticket['id']} ({ticket_url(ticket['id'])}) | Channel: {ticket['via']['channel']} → {target_ticket['id']} ({ticket_url(target_ticket['id'])})")

if __name__ == "__main__":
    main()
