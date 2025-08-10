import logging
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def main():
    query = 'type:ticket status<solved created>24hours'
    tickets = search_tickets(query)
    logging.info(f"Fetched {len(tickets)} tickets with query: {query}")

    tickets_by_group = defaultdict(list)
    excluded_channels = {"whatsapp", "any_channel"}

    for t in tickets:
        channel = t.get("via", {}).get("channel", "unknown").lower()
        if channel in excluded_channels:
            logging.debug(f"Excluded channel '{channel}' for ticket {t['id']}")
            continue

        requester_id = t["requester_id"]
        org_domains = get_requester_org_domains(requester_id)

        if ORG_DOMAIN_TO_EXCLUDE in org_domains:
            logging.info(f"⏭ Skipping ticket {t['id']} from requester {requester_id} - Organization domain '{ORG_DOMAIN_TO_EXCLUDE}' excluded")
            continue

        subject = (t.get("subject") or "").strip().lower()

        # Grouping logic based on channel type
        if channel == "side_conversation":
            key = (subject,)
        else:
            key = (requester_id, subject, channel)

        tickets_by_group[key].append(t)
        logging.debug(f"Added ticket {t['id']} to group {key}")

    for key, t_list in tickets_by_group.items():
        if len(t_list) > 1:
            t_list.sort(key=lambda x: x["created_at"])
            target_ticket = t_list[0]

            if target_ticket.get("status") in ["closed", "archived"]:
                logging.warning(f"⚠ Skipping target ticket {target_ticket['id']} because it is {target_ticket['status']}")
                continue

            if channel == "side_conversation":
                subject = key[0]
                logging.info(f"\nSubject: '{subject or '[No Subject]'}' | Channel: side_conversation")
            else:
                requester_id, subject, channel = key
                logging.info(f"\nRequester: {requester_id} | Subject: '{subject or '[No Subject]'}' | Channel: {channel}")

            logging.info(f"Target Ticket: {target_ticket['id']} ({ticket_url(target_ticket['id'])}) | Channel: {target_ticket['via']['channel']}")

            for ticket in t_list[1:]:
                merged = merge_tickets(ticket["id"], target_ticket["id"])
                if merged:
                    logging.info(f"✅ Merged Ticket {ticket['id']} ({ticket_url(ticket['id'])}) → {target_ticket['id']} ({ticket_url(target_ticket['id'])})")
                else:
                    logging.error(f"❌ Failed to merge Ticket {ticket['id']} ({ticket_url(ticket['id'])}) → {target_ticket['id']} ({ticket_url(target_ticket['id'])})")
        else:
            if channel == "side_conversation":
                subject = key[0]
                logging.info(f"ℹ No duplicates for side_conversation | Subject: '{subject or '[No Subject]'}'")
            else:
                requester_id, subject, channel = key
                logging.info(f"ℹ No duplicates for requester {requester_id} | Subject: '{subject or '[No Subject]'}' | Channel: {channel}")
