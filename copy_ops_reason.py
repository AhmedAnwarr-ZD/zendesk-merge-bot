def find_parent_for_child(child_id):
    """
    Search for a parent ticket whose side conversation external_ids.targetTicketId matches child_id.
    Does not require Ops Escalation Reason to be set.
    """
    from datetime import datetime, timezone, timedelta

    # Use timezone-aware UTC and extend to 90 days for safety
    date_90_days_ago = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

    # Search all tickets created in last 90 days
    search_url = (
        f"{BASE_URL}/search.json?"
        f"query=type:ticket created>{date_90_days_ago}"
    )

    results = zendesk_get(search_url)
    if not results:
        return None

    for t in results.get("results", []):
        side_convos = get_side_conversations(t["id"])
        for sc in side_convos:
            external_ids = sc.get("external_ids", {})
            target_id = external_ids.get("targetTicketId")
            if str(target_id) == str(child_id):
                logging.debug(f"Found parent {t['id']} for child {child_id}")
                return t["id"]

    logging.warning(f"⚠ No parent found for child ticket {child_id}")
    return None
