import os
import logging
import requests
from collections import defaultdict
from datetime import datetime

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
# API Implementations
# ------------------------
def search_tickets(query):
    """Fetch tickets from Zendesk based on query"""
    url = f"{BASE_URL}/search.json?query={query}"
    logging.debug(f"Searching tickets with URL: {url}")
    resp = requests.get(url, auth=AUTH)
    if resp.status_code != 200:
        raise Exception(f"API error {resp.status_code}: {resp.text}")
    return resp.json().get("results", [])

def get_requester_org_domains(requester_id):
    """Return org domains for a requester"""
    url = f"{BASE_URL}/users/{requester_id}.json"
    resp = requests.get(url, auth=AUTH)
    if resp.status_code != 200:
        logging.error(f"Failed to get requester {requester_id} org domains: {resp.text}")
        return []
    
    user_data = resp.json().get("user", {})
    org_id = user_data.get("organization_id")
    if not org_id:
        return []
    
    org_url = f"{BASE_URL}/organizations/{org_id}.json"
    org_resp = requests.get(org_url, auth=AUTH)
    if org_resp.status_code != 200:
        logging.error(f"Failed to get organization {org_id}: {org_resp.text}")
        return []
    
    domains = org_resp.json().get("organization", {}).get("domain_names", [])
    return [d.lower() for d in domains]

def ticket_url(ticket_id):
    """Return a full Zendesk ticket URL"""
    return f"https://{SUBDOMAIN}.zendesk.com/agent/tickets/{ticket_id}"

def merge_tickets(source_ticket_id, target_ticket_id):
    """Merge source_ticket_id into target_ticket_id"""
    url = f"{BASE_URL}/tickets/{target_ticket_id}/merge.json"
    payload = {"ids": [source_ticket_id]}
    resp = requests.post(url, json=payload, auth=AUTH)
    if resp.status_code == 200:
        return True
    logging.error(f"Merge failed ({resp.status_code}): {resp.text}")
    return False

# ------------------------
# Main Merge Logic
# ------------------------
ORG_DOMAIN_TO_EXCLUDE = "moc.gov.sa"

def main():
    query = 'type:ticket status<solved created>10minutes'
    tickets = search_tickets(query)
    logging.info(f"Fetched {len(tickets)} tickets with query: {query}")

    tickets_by_group = defaultdict(list)
    excluded_channels = {"whatsapp", "any_channel"}
    merged_summary = []

    for t in tickets:
        channel = t.get("via", {}).get("channel", "unknown").lower()
        if channel in excluded_channels:
            logging.debug(f"Excluded channel '{channel}' for ticket {t['id']}")
            continue

        requester_id = t["requester_id"]
        org_domains = get_requester_org_domains(requester_id)

        if ORG_DOMAIN_TO_EXCLUDE in org_domains:
            logging.info(f"⏭ Skipping ticket {t['id']} from requester {requester_id} - org domain excluded")
            continue

        subject = (t.get("subject") or "").strip().lower()

        if channel == "side_conversation":
            key = (subject,)
        else:
            key = (requester_id, subject, channel)

        tickets_by_group[key].append(t)

    for key, t_list in tickets_by_group.items():
        if len(t_list) > 1:
            try:
                t_list.sort(key=lambda x: datetime.fromisoformat(x.get("created_at", "").replace("Z", "+00:00")))
            except Exception:
                t_list.sort(key=lambda x: x.get("created_at", ""))

            target_ticket = t_list[0]
            target_status = (target_ticket.get("status") or "").lower()

            if target_status in ["closed", "archived"]:
                continue

            for ticket in t_list[1:]:
                if merge_tickets(ticket["id"], target_ticket["id"]):
                    logging.info(f"✅ Merged {ticket['id']} → {target_ticket['id']}")
                    merged_summary.append({"from": ticket['id'], "to": target_ticket['id']})

    logging.info("\n📊 DUPLICATE MERGE SUMMARY")
    if merged_summary:
        for m in merged_summary:
            logging.info(f"From {m['from']} → {m['to']}")
        logging.info(f"Total merged: {len(merged_summary)}")
    else:
        logging.info("No duplicates merged in this run.")

if __name__ == "__main__":
    main()
