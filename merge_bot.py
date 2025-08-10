import requests
from collections import defaultdict
import os

# Load credentials from GitHub Actions secrets
SUBDOMAIN = os.environ["SUBDOMAIN"]
EMAIL = os.environ["EMAIL"]
API_TOKEN = os.environ["API_TOKEN"]

BASE_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
AUTH = (f"{EMAIL}/token", API_TOKEN)

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
    # Search for tickets created within the last 24 hours and not solved
    query = 'type:ticket status<solved created>24hours'
    tickets = search_tickets(query)

    # Group tickets by requester
    tickets_by_requester = defaultdict(list)
    for ticket in tickets:
        tickets_by_requester[ticket["requester_id"]].append(ticket)

    for requester_id, t_list in tickets_by_requester.items():
        if len(t_list) > 1:
            # Sort tickets by creation date so oldest becomes target
            t_list.sort(key=lambda x: x["created_at"])
            target_ticket = t_list[0]

            print(f"\nRequester {requester_id}:")
            print(f"  Target Ticket: {target_ticket['id']} ({target_ticket['subject']})")

            for ticket in t_list[1:]:
                merged = merge_tickets(ticket["id"], target_ticket["id"])
                if merged:
                    print(f"    ✅ Merged Ticket {ticket['id']} ({ticket['subject']}) INTO {target_ticket['id']}")
                else:
                    print(f"    ❌ Failed to merge Ticket {ticket['id']} INTO {target_ticket['id']}")

if __name__ == "__main__":
    main()
