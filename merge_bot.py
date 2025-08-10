import requests
from collections import defaultdict
import os

SUBDOMAIN = os.environ["SUBDOMAIN"]
EMAIL = os.environ["EMAIL"]
API_TOKEN = os.environ["API_TOKEN"]

BASE_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
AUTH = (f"{EMAIL}/token", API_TOKEN)

ORG_DOMAIN_TO_EXCLUDE = "mc.gov.sa"

def ticket_url(ticket_id):
    return f"https://{SUBDOMAIN}.zendesk.com/agent/tickets/{ticket_id}"

def search_tickets(query):
    url = f"{BASE_URL}/search.json?query={query}"
    response = requests.get(url, auth=AUTH)
    response.raise_for_status()
    return response.json()["results"]

# Cache organization data per requester_id to reduce API calls
org_cache = {}

def get_requester_org_domains(requester_id):
    if requester_id in org_cache:
        return org_cache[requester_id]

    url = f"{BASE_URL}/users/{requester_id}.json"
    response = requests.get(url, auth=AUTH)
    response.raise_for_status()
    user = response.json()["user"]

    org_domains = []
    org_id = user.get("organization_id")
    if org_id:
        org_url = f"{BASE_URL}/organizations/{org_id}.json"
        org_resp = requests.get(org_url, auth=AUTH)
        org_resp.raise_for_status()
        organization = org_resp.json()["organization"]
        # org domains is a comma separated string in 'domain_names' field
        domains_str = organization.get("domain_names", "")
        org_domains = [d.strip().lower() for d in domains_str.split(",") if d.strip()]
    org_cache[requester_id] = org_domains
    return org_domains

def merge_tickets(source_id, target_id):
    url = f"{BASE_URL}/tickets/{target_id}/merge.json"
    data = {"ids": [source_id]}
    response = requests.post(url, json=data, auth=AUTH)
    response.raise_for_status()
    return response.status_code == 200

def main():
    query = 'type:ticket status<solved created>24hours'
    tickets = search_tickets(query)

    tickets_by_group = defaultdict(list)
    excluded_channels = {"whatsapp", "any_channel"}

    for t in tickets:
        channel = t.get("via", {}).get("channel", "unknown").lower()
        if channel in excluded_channels:
            continue

        requester_id = t["requester_id"]
        org_domains = get_requester_org_domains(requester_id)
        # Skip if org domain matches mc.gov.sa
        if ORG_DOMAIN_TO_EXCLUDE in org_domains:
            print(f"⏭ Skipping ticket {t['id']} from requester {requester_id} - Organization domain '{ORG_DOMAIN_TO_EXCLUDE}' excluded")
            continue

        subject = (t.get("subject") or "").strip().lower()
        tickets_by_group[(requester_id, subject, channel)].append(t)

    for (requester_id, subject, channel), t_list in tickets_by_group.items():
        if len(t_list) > 1:
            t_list.sort(key=lambda x: x["created_at"])
            target_ticket = t_list[0]

            if target_ticket.get("status") in ["closed", "archived"]:
                print(f"⚠ Skipping requester {requester_id}: Target ticket {target_ticket['id']} is {target_ticket['status']}")
                continue

            print(f"\nRequester: {requester_id} | Subject: '{subject or '[No Subject]'}' | Channel: {channel}")
            print(f"  Target Ticket: {target_ticket['id']} ({ticket_url(target_ticket['id'])}) | Channel: {target_ticket['via']['channel']}")

            for ticket in t_list[1:]:
                merged = merge_tickets(ticket["id"], target_ticket["id"])
                if merged:
                    print(f"    ✅ Merged Ticket {ticket['id']} ({ticket_url(ticket['id'])}) | Channel: {ticket['via']['channel']} → {target_ticket['id']} ({ticket_url(target_ticket['id'])})")
                else:
                    print(f"    ❌ Failed to merge Ticket {ticket['id']} ({ticket_url(ticket['id'])}) | Channel: {ticket['via']['channel']} → {target_ticket['id']} ({ticket_url(target_ticket['id'])})")
        else:
            print(f"ℹ No duplicates for requester {requester_id} | Subject: '{subject or '[No Subject]'}' | Channel: {channel}")

if __name__ == "__main__":
    main()
