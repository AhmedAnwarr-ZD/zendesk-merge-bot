import os
import logging
import requests
import time
from datetime import datetime, timezone, timedelta

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

# Rate limiting configuration
RATE_LIMIT_DELAY = 0.2  # Minimum delay between API calls (200ms)
MAX_RETRIES = 3
BACKOFF_MULTIPLIER = 2
SIDE_CONV_RATE_LIMIT = 6  # Max side conversation calls per minute (conservative)

# Search configuration
MAX_SEARCH_PAGES = 20
SEARCH_DATE_LIMIT_DAYS = 90

# Global rate limiting tracker
last_api_call_time = 0
side_conv_calls_this_minute = 0
minute_start_time = time.time()

# ------------------------
# Rate Limited API Helpers
# ------------------------
def wait_for_rate_limit():
    """Ensure we don't exceed rate limits"""
    global last_api_call_time, side_conv_calls_this_minute, minute_start_time
    
    current_time = time.time()
    
    # Reset side conversation counter every minute
    if current_time - minute_start_time >= 60:
        side_conv_calls_this_minute = 0
        minute_start_time = current_time
    
    # Ensure minimum delay between any API calls
    time_since_last_call = current_time - last_api_call_time
    if time_since_last_call < RATE_LIMIT_DELAY:
        time.sleep(RATE_LIMIT_DELAY - time_since_last_call)
    
    last_api_call_time = time.time()

def wait_for_side_conv_rate_limit():
    """Special rate limiting for side conversations endpoint"""
    global side_conv_calls_this_minute, minute_start_time
    
    current_time = time.time()
    
    # Reset counter if a minute has passed
    if current_time - minute_start_time >= 60:
        side_conv_calls_this_minute = 0
        minute_start_time = current_time
    
    # If we're at the limit, wait until the minute resets
    if side_conv_calls_this_minute >= SIDE_CONV_RATE_LIMIT:
        wait_time = 60 - (current_time - minute_start_time) + 1
        logging.info(f"Rate limit reached for side conversations. Waiting {wait_time:.1f} seconds...")
        time.sleep(wait_time)
        side_conv_calls_this_minute = 0
        minute_start_time = time.time()

def zendesk_get_with_retry(url, is_side_conv=False):
    """Make GET request with retry logic and rate limiting"""
    wait_for_rate_limit()
    
    if is_side_conv:
        wait_for_side_conv_rate_limit()
    
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, auth=AUTH)
            
            if resp.status_code == 200:
                if is_side_conv:
                    global side_conv_calls_this_minute
                    side_conv_calls_this_minute += 1
                return resp.json()
                
            elif resp.status_code == 429:  # Rate limited
                retry_after = int(resp.headers.get('Retry-After', 60))
                logging.warning(f"Rate limited on attempt {attempt + 1}. Waiting {retry_after} seconds...")
                time.sleep(retry_after)
                continue
                
            else:
                logging.error(f"GET {url} failed: {resp.status_code} {resp.text}")
                if attempt < MAX_RETRIES - 1:
                    wait_time = BACKOFF_MULTIPLIER ** attempt
                    logging.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                return None
                
        except requests.exceptions.RequestException as e:
            logging.error(f"Request exception on attempt {attempt + 1}: {e}")
            if attempt < MAX_RETRIES - 1:
                wait_time = BACKOFF_MULTIPLIER ** attempt
                logging.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            return None
    
    return None

def zendesk_put_with_retry(url, data):
    """Make PUT request with retry logic and rate limiting"""
    wait_for_rate_limit()
    
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.put(url, json=data, auth=AUTH)
            
            if resp.status_code == 200:
                return True
                
            elif resp.status_code == 429:  # Rate limited
                retry_after = int(resp.headers.get('Retry-After', 60))
                logging.warning(f"Rate limited on PUT attempt {attempt + 1}. Waiting {retry_after} seconds...")
                time.sleep(retry_after)
                continue
                
            else:
                logging.error(f"PUT {url} failed: {resp.status_code} {resp.text}")
                if attempt < MAX_RETRIES - 1:
                    wait_time = BACKOFF_MULTIPLIER ** attempt
                    logging.info(f"Retrying PUT in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                return False
                
        except requests.exceptions.RequestException as e:
            logging.error(f"PUT request exception on attempt {attempt + 1}: {e}")
            if attempt < MAX_RETRIES - 1:
                wait_time = BACKOFF_MULTIPLIER ** attempt
                logging.info(f"Retrying PUT in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            return False
    
    return False

def get_user(user_id):
    url = f"{BASE_URL}/users/{user_id}.json"
    data = zendesk_get_with_retry(url)
    return data.get("user") if data else None

def get_side_conversations(ticket_id):
    url = f"{BASE_URL}/tickets/{ticket_id}/side_conversations.json"
    data = zendesk_get_with_retry(url, is_side_conv=True)
    return data.get("side_conversations", []) if data else []

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

def get_ticket_field(ticket, field_id):
    for field in ticket.get("custom_fields", []):
        if field["id"] == field_id:
            return field.get("value")
    return None

def get_ticket(ticket_id):
    url = f"{BASE_URL}/tickets/{ticket_id}.json"
    data = zendesk_get_with_retry(url)
    return data.get("ticket") if data else None

def set_ticket_field(ticket_id, field_id, value):
    url = f"{BASE_URL}/tickets/{ticket_id}.json"
    payload = {
        "ticket": {
            "custom_fields": [
                {"id": field_id, "value": value}
            ]
        }
    }
    return zendesk_put_with_retry(url, payload)

def add_internal_note(ticket_id, body):
    url = f"{BASE_URL}/tickets/{ticket_id}.json"
    payload = {
        "ticket": {
            "comment": {
                "body": body,
                "public": False
            }
        }
    }
    return zendesk_put_with_retry(url, payload)

# ------------------------
# Optimized Search with Batching
# ------------------------
def build_parent_child_mapping(child_tickets):
    """
    Build parent-child mapping by searching more efficiently.
    Groups child tickets and searches in batches to minimize API calls.
    """
    mapping = {}
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=SEARCH_DATE_LIMIT_DAYS)).strftime("%Y-%m-%d")
    
    # Get all child IDs for reference
    child_ids = {str(ticket["id"]) for ticket in child_tickets}
    logging.info(f"Looking for parents of {len(child_ids)} child tickets")
    
    # Search with date limit and pagination control
    search_query = f"type:ticket created>={cutoff_date}"
    search_url = f"{BASE_URL}/search.json?query={requests.utils.quote(search_query)}&per_page=100"
    
    page_count = 0
    tickets_checked = 0
    
    while search_url and page_count < MAX_SEARCH_PAGES:
        data = zendesk_get_with_retry(search_url)
        if not data:
            break

        page_count += 1
        logging.info(f"Checking page {page_count} for parent tickets...")

        for ticket in data.get("results", []):
            tickets_checked += 1
            
            # Get side conversations for this ticket
            side_convos = get_side_conversations(ticket["id"])
            
            # Check if any side conversation points to our child tickets
            for sc in side_convos:
                external_ids = sc.get("external_ids", {})
                target_id = str(external_ids.get("targetTicketId", ""))
                
                if target_id in child_ids:
                    mapping[target_id] = ticket["id"]
                    logging.debug(f"Found parent {ticket['id']} for child {target_id}")
            
            # Progress update every 50 tickets
            if tickets_checked % 50 == 0:
                logging.info(f"Checked {tickets_checked} tickets, found {len(mapping)} parent relationships")

        search_url = data.get("next_page")

    logging.info(f"Mapping complete: Found {len(mapping)} parent relationships out of {len(child_ids)} child tickets")
    logging.info(f"Checked {tickets_checked} tickets across {page_count} pages")
    
    return mapping

# ------------------------
# Main Logic with Optimized Processing
# ------------------------
def main():
    logging.info("Starting Zendesk ticket processing...")
    
    # Get all child tickets from the view
    tickets = get_tickets_from_view(VIEW_ID)
    logging.info(f"Found {len(tickets)} tickets in view {VIEW_ID}.")
    
    if not tickets:
        logging.info("No tickets to process.")
        return

    # Build parent-child mapping efficiently
    logging.info("Building parent-child mapping...")
    parent_mapping = build_parent_child_mapping(tickets)
    
    # Cache for users and parent tickets
    user_cache = {}
    parent_ticket_cache = {}

    # Track statistics
    success_count = 0
    no_parent_count = 0
    error_count = 0

    # Process each child ticket
    for i, child_ticket in enumerate(tickets, 1):
        child_id = str(child_ticket["id"])
        child_requester_id = child_ticket["requester_id"]
        
        logging.info(f"Processing ticket {i}/{len(tickets)}: {child_id}")

        try:
            # Look up parent from our mapping
            parent_id = parent_mapping.get(child_id)
            
            if not parent_id:
                logging.warning(f"⚠ Ticket {child_id} — no parent found.")
                no_parent_count += 1
                continue

            # Get parent ticket details (with caching)
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
                # Copy the escalation reason to child ticket
                if set_ticket_field(child_id, OPS_ESCALATION_REASON_ID, parent_value):
                    logging.info(f"✅ Copied Ops Escalation Reason from parent {parent_id} → child {child_id}")
                    success_count += 1
                else:
                    logging.error(f"❌ Failed to update child ticket {child_id}")
                    error_count += 1
            else:
                # Parent missing escalation reason - add note to parent
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

    # Print final summary
    logging.info(f"\n=== FINAL SUMMARY ===")
    logging.info(f"Total tickets processed: {len(tickets)}")
    logging.info(f"Parent relationships found: {len(parent_mapping)}")
    logging.info(f"Successful updates: {success_count}")
    logging.info(f"No parent found: {no_parent_count}")
    logging.info(f"Errors: {error_count}")
    logging.info(f"Completion rate: {((success_count + no_parent_count) / len(tickets) * 100):.1f}%")

if __name__ == "__main__":
    main()
