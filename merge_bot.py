import logging
from collections import defaultdict
from datetime import datetime

logging.basicConfig(
    level=logging.DEBUG,  # Show debug messages in GitHub Actions logs
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# ------------------------
# External API Functions
# ------------------------
# These must be implemented according to your Zendesk API integration
# Placeholders here just for structure
def search_tickets(query):
    """Fetch tickets from Zendesk based on query"""
    raise NotImplementedError

def get_requester_org_domains(requester_id):
    """Return org domains for a requester"""
    raise NotImplementedError

def ticket_url(ticket_id):
    """Return a full Zendesk ticket URL"""
    return f"https://shopaleena.zendesk.com/agent/tickets/{ticket_id}"

def merge_tickets(source_ticket_id, target_ticket_id):
    """Merge source_ticket_id into target_ticket_id"""
    raise NotImplementedError


# ------------------------
# Main Merge Logic
# ------------------------
ORG_DOMAIN_TO_EXCLUDE = "moc.gov.sa"  # Replace with your excluded domain

def main():
    query = 'type:ticket status<solved created>10minutes'
    tickets = search_tickets(query)
    logging.info(f"Fetched {len(tickets)} tickets with query: {query}")

    tickets_by_group = defaultdict(list)
    excluded_channels = {"whatsapp", "any_channel"}

    merged_summary = []  # Store merges for summary

    for t in tickets:
        channel = t.get("via", {}).get("channel", "unknown").lower()
        if channel in excluded_channels:
            logging.debug(f"Excluded channel '{channel}' for ticket {t['id']}")
            continue

        requester_id = t["requester_id"]
        org_domains = get_requester_org_domains(requester_id)

        if ORG_DOMAIN_TO_EXCLUDE in org_domains:
            logging.info(
                f"⏭ Skipping ticket {t['id']} from requester {requester_id} - "
                f"Organization domain 'moc.gov.sa' excluded"
            )
            continue

        subject = (t.get("subject") or "").strip().lower()

        # Group key
        if channel == "side_conversation":
            key = (subject,)
        else:
            key = (requester_id, subject, channel)

        tickets_by_group[key].append(t)
        logging.debug(f"Added ticket {t['id']} to group {key}")

    for key, t_list in tickets_by_group.items():
        is_side_conversation = (len(key) == 1)

        if len(t_list) > 1:
            # Sort tickets by created_at
            def _created_at_str(x):
                return x.get("created_at", "")

            try:
                t_list.sort(
                    key=lambda x: datetime.fromisoformat(
                        x.get("created_at", "").replace("Z", "+00:00")
                    )
                )
            except Exception:
                t_list.sort(key=_created_at_str)

            target_ticket = t_list[0]
            target_status = (target_ticket.get("status") or "").lower()

            if target_status in ["closed", "archived"]:
                logging.warning(
                    f"⚠ Skipping target ticket {target_ticket['id']} because it is {target_status}"
                )
                continue

            if is_side_conversation:
                subject = key[0]
                logging.info(
                    f"\nSubject: '{subject or '[No Subject]'}' | Channel: side_conversation"
                )
            else:
                requester_id, subject, group_channel = key
                logging.info(
                    f"\nRequester: {requester_id} | Subject: '{subject or '[No Subject]'}' | Channel: {group_channel}"
                )

            target_channel = target_ticket.get("via", {}).get("channel", "unknown")
            logging.info(
                f"Target Ticket: {target_ticket['id']} ({ticket_url(target_ticket['id'])}) | Channel: {target_channel}"
            )

            for ticket in t_list[1:]:
                merged = merge_tickets(ticket["id"], target_ticket["id"])
                ticket_channel = ticket.get("via", {}).get("channel", "unknown")
                if merged:
                    logging.info(
                        f"✅ Merged Ticket {ticket['id']} ({ticket_url(ticket['id'])}) → "
                        f"{target_ticket['id']} ({ticket_url(target_ticket['id'])}) | Channel: {ticket_channel}"
                    )
                    merged_summary.append({
                        "from": ticket['id'],
                        "to": target_ticket['id'],
                        "channel": ticket_channel
                    })
                else:
                    logging.error(
                        f"❌ Failed to merge Ticket {ticket['id']} ({ticket_url(ticket['id'])}) → "
                        f"{target_ticket['id']} ({ticket_url(target_ticket['id'])}) | Channel: {ticket_channel}"
                    )
        else:
            if is_side_conversation:
                subject = key[0]
                logging.info(
                    f"ℹ No duplicates for side_conversation | Subject: '{subject or '[No Subject]'}'"
                )
            else:
                requester_id, subject, group_channel = key
                logging.info(
                    f"ℹ No duplicates for requester {requester_id} | Subject: '{subject or '[No Subject]'}' | Channel: {group_channel}"
                )

    # ------------------------
    # Summary Log
    # ------------------------
    logging.info("\n" + "="*50)
    logging.info("📊 DUPLICATE MERGE SUMMARY")
    logging.info("="*50)
    if merged_summary:
        for m in merged_summary:
            logging.info(f"From {m['from']} → {m['to']} | Channel: {m['channel']}")
        logging.info(f"Total merged: {len(merged_summary)}")
    else:
        logging.info("No duplicates merged in this run.")
    logging.info("="*50)


if __name__ == "__main__":
    main()
