# ------------------------
# User Helper
# ------------------------
def get_user(user_id):
    """Fetch user details by user ID."""
    url = f"{BASE_URL}/users/{user_id}.json"
    data = zendesk_get(url)
    if data and "user" in data:
        return data["user"]
    return None

# ------------------------
# Main Logic
# ------------------------
def main():
    tickets = get_tickets_from_view(VIEW_ID)
    logging.info(f"Found {len(tickets)} tickets in view {VIEW_ID}.")

    # Cache parents to reduce API calls
    parent_cache = {}
    user_cache = {}

    for child_ticket in tickets:
        child_id = child_ticket["id"]
        child_requester_id = child_ticket["requester_id"]

        # Find parent ticket
        parent_id = find_parent_for_child(child_id, parent_cache)
        if not parent_id:
            logging.warning(f"⚠ Ticket {child_id} — no parent found via external_ids.targetTicketId.")
            continue

        if parent_id not in parent_cache:
            parent_ticket = get_ticket(parent_id)
            if not parent_ticket:
                logging.warning(f"⚠ Failed to fetch parent {parent_id} for child {child_id}.")
                continue
            parent_cache[parent_id] = parent_ticket
        else:
            parent_ticket = parent_cache[parent_id]

        parent_value = get_ticket_field(parent_ticket, OPS_ESCALATION_REASON_ID)

        if parent_value:
            if set_ticket_field(child_id, OPS_ESCALATION_REASON_ID, parent_value):
                logging.info(f"✅ Copied Ops Escalation Reason from parent {parent_id} → child {child_id}")
            else:
                logging.error(f"❌ Failed to update child ticket {child_id}")
        else:
            # Fetch assignee name
            assignee_id = parent_ticket.get("assignee_id")
            if assignee_id in user_cache:
                assignee_name = user_cache[assignee_id]
            else:
                assignee = get_user(assignee_id)
                assignee_name = assignee["name"] if assignee else f"ID:{assignee_id}"
                user_cache[assignee_id] = assignee_name

            # Fetch child requester name
            if child_requester_id in user_cache:
                requester_name = user_cache[child_requester_id]
            else:
                requester = get_user(child_requester_id)
                requester_name = requester["name"] if requester else f"ID:{child_requester_id}"
                user_cache[child_requester_id] = requester_name

            note_body = (
                f"⚠ Ops Escalation Reason missing in parent ticket {parent_id}. "
                f"Assignee in parent: {assignee_name}, "
                f"Child requester: {requester_name}"
            )

            if add_internal_note(child_id, note_body):
                logging.info(f"✅ Added internal note to child {child_id} mentioning missing Ops Escalation Reason")
            else:
                logging.error(f"❌ Failed to add internal note to child ticket {child_id}")

if __name__ == "__main__":
    main()
