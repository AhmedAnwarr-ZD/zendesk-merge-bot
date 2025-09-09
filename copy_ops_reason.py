import os
import logging
import requests
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

SUBDOMAIN = os.environ["SUBDOMAIN"]
EMAIL = os.environ["EMAIL"]
API_TOKEN = os.environ["API_TOKEN"]

BASE_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
AUTH = (f"{EMAIL}/token", API_TOKEN)

OPS_ESCALATION_REASON_ID = 20837946693533
VIEW_ID = 27529425733661  # Ops Escalation Reason Empty

# Rate limiting config
RATE_LIMIT_DELAY = 0.2
MAX_RETRIES = 3
BACKOFF_MULTIPLIER = 2

last_api_call_time = 0

INCLUDE_VIA = "include=via_source"  # <-- force Zendesk to return via.source.{from,rel}

DEBUG_DUMP_LIMIT = 5  # how many unmatched 'via' payloads to print for inspection
debug_dumped = 0

def wait_for_rate_limit():
    global last_api_call_time
    now = time.time()
    elapsed = now - last_api_call_time
    if elapsed < RATE_LIMIT_DELAY:
        time.sleep(RATE_LIMIT_DELAY - elapsed)
    last_api_call_time = time.time()

def zendesk_get_with_retry(url):
    wait_for_rate_limit()
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, auth=AUTH)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                logging.warning(f"Rate limited on attempt {attempt+1}. Waiting {retry_after}s...")
                time.sleep(retry_after)
                continue
            logging.error(f"GET {url} failed: {resp.status_code} {resp.text}")
            if attempt < MAX_RETRIES - 1:
                wait_time = BACKOFF_MULTIPLIER ** attempt
                logging.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Request exception on attempt {attempt+1}: {e}")
            if attempt < MAX_RETRIES - 1:
                wait_time = BACKOFF_MULTIPLIER ** attempt
                logging.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            return None
    return None

def zendesk_put_with_retry(url, data):
    wait_for_rate_limit()
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.put(url, json=data, auth=AUTH)
            if resp.status_code == 200:
                return True
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                logging.warning(f"Rate limited on PUT attempt {attempt+1}. Waiting {retry_after}s...")
                time.sleep(retry_after)
                continue
            logging.error(f"PUT {url} failed: {resp.status_code} {resp.text}")
            if attempt < MAX_RETRIES - 1:
                wait_time = BACKOFF_MULTIPLIER ** attempt
                logging.info(f"Retrying PUT in {wait_time}s...")
                time.sleep(wait_time)
                continue
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"PUT request exception on attempt {attempt+1}: {e}")
            if attempt < MAX_RETRIES - 1:
                wait_time = BACKOFF_MULTIPLIER ** attempt
                logging.info(f"Retrying PUT in {wait_time}s...")
                time.sleep(wait_time)
                continue
            return False
    return False

def get_tickets_from_view(view_id):
    url = f"{BASE_URL}/views/{view_id}/tickets.json"
    tickets = []
    while url:
        data = zendesk_get_with_retry(url)
        if not data:
            break
        tickets.extend(data.get("tickets", []))
        url = data.get("next_page")
    return tickets

def get_ticket(ticket_id):
    # IMPORTANT: include=via_source to expand via.source.from / via.source.rel
    url = f"{BASE_URL}/tickets/{ticket_id}.json?{INCLUDE_VIA}"
    data = zendesk_get_with_retry(url)
    return data.get("ticket") if data else None

def get_ticket_audits(ticket_id):
    # include=via_source also works on audits
    url = f"{BASE_URL}/tickets/{ticket_id}/audits.json?{INCLUDE_VIA}"
    data = zendesk_get_with_retry(url)
    return data.get("audits", []) if data else []

def get_user(user_id):
    url = f"{BASE_URL}/users/{user_id}.json"
    data = zendesk_get_with_retry(url)
    return data.get("user") if data else None

def get_ticket_field(ticket, field_id):
    for field in ticket.get("custom_fields", []):
        if field["id"] == field_id:
            return field.get("value")
    return None

def set_ticket_field(ticket_id, field_id, value):
    url = f"{BASE_URL}/tickets/{ticket_id}.json"
    payload = {"ticket": {"custom_fields": [{"id": field_id, "value": value}]}}
    return zendesk_put_with_retry(url, payload)

def add_internal_note(ticket_id, body):
    url = f"{BASE_URL}/tickets/{ticket_id}.json"
    payload = {"ticket": {"comment": {"body": body, "public": False}}}
    return zendesk_put_with_retry(url, payload)

# ---------- Parent detection helpers ----------
def parent_from_ticket_via(ticket_obj):
    """
    Prefer the direct 'via' path when present on /tickets/{id}.json.
    We accept:
      - via.channel in {"side_conversation", "side_conversation_ticket"}
      - OR via.source.rel == "side_conversation" (some tenants return 'api' channel)
    """
    via = ticket_obj.get("via") or {}
    channel = (via.get("channel") or "").lower()
    src = (via.get("source") or {})
    rel = (src.get("rel") or "").lower()
    from_obj = (src.get("from") or {})
    from_type = (from_obj.get("type") or "").lower()
    parent_id = from_obj.get("id")

    is_sc_channel = channel in ("side_conversation", "side_conversation_ticket")
    is_sc_rel = rel == "side_conversation"

    if (is_sc_channel or is_sc_rel) and from_type == "ticket" and parent_id:
        try:
            return int(parent_id)
        except (TypeError, ValueError):
            return None
    return None

def parent_from_audits(ticket_id):
    """
    Fallback: scan audits; find a side-conversation creation audit,
    then read source.from.id. (Audits sometimes mark channel 'api' with rel 'side_conversation'.)
    """
    audits = get_ticket_audits(ticket_id)
    for audit in audits:
        via = audit.get("via") or {}
        channel = (via.get("channel") or "").lower()
        src = (via.get("source") or {})
        rel = (src.get("rel") or "").lower()
        from_obj = (src.get("from") or {})
        from_type = (from_obj.get("type") or "").lower()
        parent_id = from_obj.get("id")

        is_sc_channel = channel in ("side_conversation", "side_conversation_ticket")
        is_sc_rel = rel == "side_conversation"

        if (is_sc_channel or is_sc_rel) and from_type == "ticket" and parent_id:
            try:
                return int(parent_id)
            except (TypeError, ValueError):
                continue
    return None

# ---------- Mapping using robust per-ticket fetch ----------
def build_parent_child_mapping(child_tickets):
    global debug_dumped
    mapping = {}
    child_ids = [int(t["id"]) for t in child_tickets]
    logging.info(f"Looking for parents of {len(child_ids)} child tickets")

    checked = 0
    for cid in child_ids:
        t = get_ticket(cid)
        checked += 1
        parent_id = None

        if t:
            parent_id = parent_from_ticket_via(t)

        if not parent_id:
            # Fallback to audits only if needed
            parent_id = parent_from_audits(cid)

        if parent_id:
            mapping[str(cid)] = parent_id
        else:
            # dump the via we actually got for debugging (first few only)
            if t and debug_dumped < DEBUG_DUMP_LIMIT:
                logging.warning("DEBUG via for child %s: %s", cid, t.get("via"))
                debug_dumped += 1

        if checked % 25 == 0 or checked == len(child_ids):
            logging.info(f"Checked {checked} child tickets, mapped {len(mapping)} parents so far")

    logging.info(f"Mapping complete: Found {len(mapping)} parent relationships out of {len(child_ids)}")
    logging.info(f"Checked {checked} tickets in {len(child_ids)} single-ticket calls")
    return mapping

# ---------- Main ----------
def main():
    logging.info("Starting Zendesk ticket processing...")

    tickets = get_tickets_from_view(VIEW_ID)
    logging.info(f"Found {len(tickets)} tickets in view {VIEW_ID}.")

    if not tickets:
        logging.info("No tickets to process.")
        return

    logging.info("Building parent-child mapping...")
    parent_mapping = build_parent_child_mapping(tickets)

    user_cache = {}
    parent_ticket_cache = {}

    success_count = 0
    no_parent_count = 0
    error_count = 0

    for i, child_ticket in enumerate(tickets, 1):
        child_id = str(child_ticket["id"])
        child_requester_id = child_ticket["requester_id"]

        logging.info(f"Processing ticket {i}/{len(tickets)}: {child_id}")

        try:
            parent_id = parent_mapping.get(child_id)
            if not parent_id:
                logging.warning(f"⚠ Ticket {child_id} — no parent found.")
                no_parent_count += 1
                continue

            if parent_id not in parent_ticket_cache:
                parent_ticket = get_ticket(parent_id)
                if not parent_ticket:
                    logging.warning(f"⚠ Failed to fetch parent {parent_id} for child {child_id}.")
                    error_count += 1
                    continue
                parent_ticket_cache[parent_id] = parent_ticket
            else:
                parent_ticket = parent_ticket_cache[parent_id]

            parent_value = get_ticket_field(parent_ticket, OPS_ESCALATION_REASON_ID)

            if parent_value:
                if set_ticket_field(child_id, OPS_ESCALATION_REASON_ID, parent_value):
                    logging.info(f"✅ Copied Ops Escalation Reason from parent {parent_id} → child {child_id}")
                    success_count += 1
                else:
                    logging.error(f"❌ Failed to update child ticket {child_id}")
                    error_count += 1
            else:
                assignee_id = parent_ticket.get("assignee_id")
                if assignee_id in user_cache:
                    assignee_name = user_cache[assignee_id]
                else:
                    assignee = get_user(assignee_id)
                    assignee_name = assignee["name"] if assignee else f"ID:{assignee_id}"
                    user_cache[assignee_id] = assignee_name
                assignee_link = f"https://{SUBDOMAIN}.zendesk.com/users/{assignee_id}"

                if child_requester_id in user_cache:
                    requester_name = user_cache[child_requester_id]
                else:
                    requester = get_user(child_requester_id)
                    requester_name = requester["name"] if requester else f"ID:{child_requester_id}"
                    user_cache[child_requester_id] = requester_name
                requester_link = f"https://{SUBDOMAIN}.zendesk.com/users/{child_requester_id}"

                note_body = (
                    f"⚠ Ops Escalation Reason missing in parent ticket {parent_id}. "
                    f"Assignee in parent: [{assignee_name}]({assignee_link}), "
                    f"Child requester: [{requester_name}]({requester_link})"
                )

                if add_internal_note(parent_id, note_body):
                    logging.info(f"✅ Added internal note to parent {parent_id} mentioning missing Ops Escalation Reason")
                else:
                    logging.error(f"❌ Failed to add internal note to parent ticket {parent_id}")
                    error_count += 1

        except Exception as e:
            logging.error(f"❌ Unexpected error processing ticket {child_id}: {e}")
            error_count += 1

    logging.info(f"\n=== FINAL SUMMARY ===")
    logging.info(f"Total tickets processed: {len(tickets)}")
    logging.info(f"Parent relationships found: {len(parent_mapping)}")
    logging.info(f"Successful updates: {success_count}")
    logging.info(f"No parent found: {no_parent_count}")
    logging.info(f"Errors: {error_count}")
    completion = ((success_count + no_parent_count) / len(tickets) * 100) if tickets else 100.0
    logging.info(f"Completion rate: {completion:.1f}%")

if __name__ == "__main__":
    main()
