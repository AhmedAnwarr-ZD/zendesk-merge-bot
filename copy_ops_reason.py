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
    url = f"{BASE_URL}/tickets/{ticket_id}.json"
    data = zendesk_get_with_retry(url)
    return data.get("ticket") if data else None

def get_user(user_id):
    url = f"{BASE_URL}/users/{user_id}.json"
    data = zendesk_get_with_retry(url)
    return data.get("user") if data else None

def find_parent_reference_field():
    """Find where Zendesk stores the parent ticket reference for side conversations"""
    
    # Get the known side conversation tickets
    side_conversation_tickets = [201580, 201804]
    expected_parents = [201576, 201796]
    
    for i, child_id in enumerate(side_conversation_tickets):
        expected_parent = expected_parents[i]
        
        print(f"\n{'='*60}")
        print(f"ANALYZING SIDE CONVERSATION TICKET: {child_id}")
        print(f"Expected parent: {expected_parent}")
        print(f"{'='*60}")
        
        # Get full ticket data
        child_ticket = get_ticket(child_id)
        if not child_ticket:
            print(f"❌ Could not fetch ticket {child_id}")
            continue
        
        print(f"✅ Fetched ticket {child_id}")
        
        # Look through ALL fields for the parent reference
        print(f"\n📋 CUSTOM FIELDS:")
        custom_fields = child_ticket.get('custom_fields', [])
        for field in custom_fields:
            field_id = field.get('id')
            field_value = field.get('value')
            if field_value:  # Only show fields with values
                print(f"  Field {field_id}: {field_value}")
                # Check if this field contains the parent ticket ID
                if str(expected_parent) in str(field_value):
                    print(f"    ⭐ FOUND PARENT REFERENCE! Field {field_id} contains {expected_parent}")
        
        print(f"\n📝 TICKET PROPERTIES:")
        # Check various ticket properties that might contain parent reference
        properties_to_check = [
            'external_id', 'problem_id', 'forum_topic_id', 'group_id',
            'organization_id', 'brand_id', 'ticket_form_id',
            'raw_subject', 'description', 'tags'
        ]
        
        for prop in properties_to_check:
            value = child_ticket.get(prop)
            if value:
                print(f"  {prop}: {value}")
                if str(expected_parent) in str(value):
                    print(f"    ⭐ FOUND PARENT REFERENCE in {prop}!")
        
        print(f"\n📧 VIA INFORMATION:")
        via = child_ticket.get('via', {})
        print(f"  Channel: {via.get('channel')}")
        print(f"  Source: {via.get('source', {})}")
        
        # Check if via source contains parent reference
        source = via.get('source', {})
        for key, value in source.items():
            if value and str(expected_parent) in str(value):
                print(f"    ⭐ FOUND PARENT REFERENCE in via.source.{key}!")
        
        print(f"\n🏷️ TAGS:")
        tags = child_ticket.get('tags', [])
        for tag in tags:
            print(f"  Tag: {tag}")
            if str(expected_parent) in tag:
                print(f"    ⭐ FOUND PARENT REFERENCE in tag!")
        
        print(f"\n🔗 RELATED INFORMATION:")
        # Check other possible fields
        other_fields = ['url', 'created_at', 'updated_at', 'type', 'subject', 'raw_subject']
        for field in other_fields:
            value = child_ticket.get(field)
            if value and str(expected_parent) in str(value):
                print(f"    ⭐ FOUND PARENT REFERENCE in {field}!")
        
        # Print the entire ticket structure (truncated) for manual inspection
        print(f"\n📋 FULL TICKET STRUCTURE (first 2000 chars):")
        import json
        full_ticket_str = json.dumps(child_ticket, indent=2, default=str)
        print(full_ticket_str[:2000])
        if len(full_ticket_str) > 2000:
            print("... (truncated)")
        
        # Specifically search for the parent ID anywhere in the ticket data
        if str(expected_parent) in full_ticket_str:
            print(f"\n🎯 PARENT ID {expected_parent} FOUND SOMEWHERE IN TICKET DATA!")
            # Find the exact location
            lines = full_ticket_str.split('\n')
            for line_num, line in enumerate(lines):
                if str(expected_parent) in line:
                    print(f"  Line {line_num}: {line.strip()}")
        else:
            print(f"\n❌ Parent ID {expected_parent} NOT found in ticket data")

# Run this to find where the parent reference is stored
if __name__ == "__main__":
    find_parent_reference_field()

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

def main():
    logging.info("Starting Zendesk side conversation processing...")

    tickets = get_tickets_from_view(VIEW_ID)
    logging.info(f"Found {len(tickets)} tickets in view {VIEW_ID}.")

    if not tickets:
        logging.info("No tickets to process.")
        return

    # Build parent-child mapping using the working method
    logging.info("Finding parent relationships...")
    parent_mapping = {}
    
    for ticket in tickets:
        child_id = ticket['id']
        parent_id = find_parent_ticket_id(ticket)
        if parent_id:
            parent_mapping[str(child_id)] = parent_id
            logging.info(f"Found parent relationship: {child_id} → {parent_id}")
        else:
            logging.warning(f"No parent found for ticket {child_id}")
    
    logging.info(f"Found {len(parent_mapping)} parent relationships out of {len(tickets)} tickets")

    if not parent_mapping:
        logging.error("No parent relationships found!")
        return

    # Process each child ticket
    user_cache = {}
    parent_ticket_cache = {}
    
    success_count = 0
    no_parent_count = 0
    missing_field_count = 0
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

            # Get parent ticket (with caching)
            if parent_id not in parent_ticket_cache:
                parent_ticket = get_ticket(parent_id)
                if not parent_ticket:
                    logging.warning(f"⚠ Failed to fetch parent {parent_id} for child {child_id}.")
                    error_count += 1
                    continue
                parent_ticket_cache[parent_id] = parent_ticket
            else:
                parent_ticket = parent_ticket_cache[parent_id]

            # Check if parent has Ops Escalation Reason
            parent_value = get_ticket_field(parent_ticket, OPS_ESCALATION_REASON_ID)

            if parent_value:
                # Copy the field value to child
                if set_ticket_field(child_id, OPS_ESCALATION_REASON_ID, parent_value):
                    logging.info(f"✅ Copied Ops Escalation Reason '{parent_value}' from parent {parent_id} → child {child_id}")
                    success_count += 1
                else:
                    logging.error(f"❌ Failed to update child ticket {child_id}")
                    error_count += 1
            else:
                # Parent doesn't have the field - add internal note
                logging.info(f"Parent {parent_id} has no Ops Escalation Reason - adding note")
                
                # Get user info for the note (with caching)
                assignee_id = parent_ticket.get("assignee_id")
                if assignee_id:
                    if assignee_id in user_cache:
                        assignee_name = user_cache[assignee_id]
                    else:
                        assignee = get_user(assignee_id)
                        assignee_name = assignee["name"] if assignee else f"ID:{assignee_id}"
                        user_cache[assignee_id] = assignee_name
                    assignee_link = f"https://{SUBDOMAIN}.zendesk.com/users/{assignee_id}"
                else:
                    assignee_name = "Unassigned"
                    assignee_link = ""

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
                    logging.info(f"✅ Added internal note to parent {parent_id}")
                    missing_field_count += 1
                else:
                    logging.error(f"❌ Failed to add internal note to parent {parent_id}")
                    error_count += 1

        except Exception as e:
            logging.error(f"❌ Unexpected error processing ticket {child_id}: {e}")
            error_count += 1

    # Final summary
    logging.info(f"\n=== FINAL SUMMARY ===")
    logging.info(f"Total tickets processed: {len(tickets)}")
    logging.info(f"Parent relationships found: {len(parent_mapping)}")
    logging.info(f"Successfully copied Ops Escalation Reason: {success_count}")
    logging.info(f"Added notes for missing parent field: {missing_field_count}")
    logging.info(f"No parent found: {no_parent_count}")
    logging.info(f"Errors: {error_count}")
    
    total_processed = success_count + missing_field_count + no_parent_count
    completion = (total_processed / len(tickets) * 100) if tickets else 100.0
    logging.info(f"Completion rate: {completion:.1f}%")

if __name__ == "__main__":
    main()
