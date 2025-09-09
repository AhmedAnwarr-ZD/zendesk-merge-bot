import os
import logging
import requests
import time
import json
from pprint import pprint

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

VIEW_ID = 27529425733661  # Ops Escalation Reason Empty

# Rate limiting
RATE_LIMIT_DELAY = 0.2
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
    try:
        resp = requests.get(url, auth=AUTH)
        if resp.status_code == 200:
            return resp.json()
        logging.error(f"GET {url} failed: {resp.status_code} {resp.text}")
        return None
    except Exception as e:
        logging.error(f"Request exception: {e}")
        return None

def deep_analyze_ticket(ticket_id):
    """Comprehensive analysis of a single ticket"""
    logging.info(f"\n{'='*60}")
    logging.info(f"DEEP ANALYSIS OF TICKET {ticket_id}")
    logging.info(f"{'='*60}")
    
    # 1. Basic ticket info
    logging.info("1. BASIC TICKET DATA:")
    url = f"{BASE_URL}/tickets/{ticket_id}.json"
    basic_data = zendesk_get_with_retry(url)
    if basic_data:
        ticket = basic_data['ticket']
        logging.info(f"   ID: {ticket['id']}")
        logging.info(f"   Subject: {ticket['subject']}")
        logging.info(f"   Status: {ticket['status']}")
        logging.info(f"   Created: {ticket['created_at']}")
        logging.info(f"   Requester ID: {ticket['requester_id']}")
        logging.info(f"   Assignee ID: {ticket.get('assignee_id', 'None')}")
        
        # Show via structure
        logging.info("\n   VIA STRUCTURE:")
        via = ticket.get('via', {})
        logging.info(f"   {json.dumps(via, indent=6)}")
    
    # 2. Try all possible API endpoints for this ticket
    endpoints_to_try = [
        ("Basic", f"{BASE_URL}/tickets/{ticket_id}.json"),
        ("With audits", f"{BASE_URL}/tickets/{ticket_id}.json?include=audits"),
        ("With users", f"{BASE_URL}/tickets/{ticket_id}.json?include=users"),
        ("With via_source", f"{BASE_URL}/tickets/{ticket_id}.json?include=via_source"),
        ("With side_conversations", f"{BASE_URL}/tickets/{ticket_id}.json?include=side_conversations"),
        ("All includes", f"{BASE_URL}/tickets/{ticket_id}.json?include=audits,users,via_source,side_conversations"),
        ("Audits endpoint", f"{BASE_URL}/tickets/{ticket_id}/audits.json"),
        ("Audits with includes", f"{BASE_URL}/tickets/{ticket_id}/audits.json?include=users,via_source"),
        ("Comments endpoint", f"{BASE_URL}/tickets/{ticket_id}/comments.json"),
        ("Side conversations", f"{BASE_URL}/tickets/{ticket_id}/side_conversations.json"),
    ]
    
    logging.info(f"\n2. TRYING ALL API ENDPOINTS:")
    for name, url in endpoints_to_try:
        logging.info(f"\n   {name}: {url}")
        data = zendesk_get_with_retry(url)
        if data:
            # Check for any parent/relationship clues in the response
            data_str = json.dumps(data)
            potential_tickets = set()
            
            # Look for any ticket IDs in the response
            import re
            ticket_matches = re.findall(r'"id":\s*(\d{6,})', data_str)
            for match in ticket_matches:
                if int(match) != int(ticket_id):
                    potential_tickets.add(match)
            
            # Look for URLs
            url_matches = re.findall(rf'https://{SUBDOMAIN}\.zendesk\.com/[^"]*?(\d{{6,}})', data_str)
            potential_tickets.update(url_matches)
            
            if potential_tickets:
                logging.info(f"      → Found potential related ticket IDs: {', '.join(potential_tickets)}")
            else:
                logging.info(f"      → No related ticket IDs found")
                
            # Show key structure elements
            if 'ticket' in data:
                ticket_data = data['ticket']
                if 'via' in ticket_data:
                    logging.info(f"      → Via: {json.dumps(ticket_data['via'], indent=8)}")
            
            if 'audits' in data:
                audits = data['audits']
                logging.info(f"      → Found {len(audits)} audits")
                for i, audit in enumerate(audits[:3]):  # Show first 3 audits
                    logging.info(f"         Audit {i+1}: ID {audit.get('id')}, Events: {len(audit.get('events', []))}")
                    for j, event in enumerate(audit.get('events', [])[:2]):  # First 2 events
                        event_type = event.get('type', 'Unknown')
                        logging.info(f"            Event {j+1}: {event_type}")
                        if event_type == 'Comment':
                            body = event.get('body', '')[:200]
                            html_body = event.get('html_body', '')[:200]
                            logging.info(f"               Body preview: {body}")
                            if html_body != body:
                                logging.info(f"               HTML preview: {html_body}")
            
            if 'side_conversations' in data:
                side_convs = data['side_conversations']
                logging.info(f"      → Found {len(side_convs)} side conversations")
                for i, conv in enumerate(side_convs):
                    logging.info(f"         Side conv {i+1}: {json.dumps(conv, indent=10)}")
        else:
            logging.info(f"      → Failed to retrieve data")
    
    # 3. Try to find any relationships via search
    logging.info(f"\n3. SEARCHING FOR RELATIONSHIPS:")
    
    # Search for tickets that might reference this one
    search_url = f"{BASE_URL}/search.json?query=type:ticket {ticket_id}"
    search_data = zendesk_get_with_retry(search_url)
    if search_data and search_data.get('results'):
        logging.info(f"   Found {len(search_data['results'])} tickets that reference {ticket_id}")
        for result in search_data['results'][:5]:  # Show first 5
            logging.info(f"      → Ticket {result['id']}: {result.get('subject', 'No subject')}")
    else:
        logging.info(f"   No tickets found that reference {ticket_id}")
    
    # Also search in the subject/description
    if basic_data:
        subject = basic_data['ticket'].get('subject', '')
        description = basic_data['ticket'].get('description', '')
        
        # Look for ticket references in subject and description
        logging.info(f"\n4. ANALYZING TICKET CONTENT FOR REFERENCES:")
        logging.info(f"   Subject: {subject}")
        logging.info(f"   Description preview: {description[:300]}")
        
        # Extract any numbers that could be ticket IDs
        import re
        potential_ids = re.findall(r'\b(\d{6,})\b', f"{subject} {description}")
        potential_ids = [pid for pid in potential_ids if int(pid) != int(ticket_id)]
        if potential_ids:
            logging.info(f"   Potential parent ticket IDs from content: {potential_ids}")
        else:
            logging.info(f"   No potential ticket IDs found in content")

def main():
    logging.info("Starting comprehensive Zendesk diagnostic...")
    
    # Get tickets from view
    url = f"{BASE_URL}/views/{VIEW_ID}/tickets.json"
    data = zendesk_get_with_retry(url)
    if not data:
        logging.error("Failed to get tickets from view")
        return
    
    tickets = data.get('tickets', [])
    logging.info(f"Found {len(tickets)} tickets in view")
    
    if not tickets:
        logging.info("No tickets to analyze")
        return
    
    # Analyze the first few tickets in detail
    tickets_to_analyze = min(3, len(tickets))
    logging.info(f"Will deep-analyze first {tickets_to_analyze} tickets")
    
    for i, ticket in enumerate(tickets[:tickets_to_analyze]):
        deep_analyze_ticket(ticket['id'])
        
        if i < tickets_to_analyze - 1:
            logging.info(f"\nWaiting before next analysis...")
            time.sleep(2)  # Pause between analyses
    
    # Summary analysis
    logging.info(f"\n{'='*60}")
    logging.info("SUMMARY ANALYSIS")
    logging.info(f"{'='*60}")
    
    all_subjects = [t.get('subject', '') for t in tickets]
    all_ids = [str(t['id']) for t in tickets]
    
    logging.info("All ticket IDs in view:")
    logging.info(f"   {', '.join(all_ids)}")
    
    logging.info("\nAll subjects:")
    for ticket in tickets:
        logging.info(f"   {ticket['id']}: {ticket.get('subject', 'No subject')}")
    
    # Look for patterns in subjects that might indicate relationships
    logging.info("\nLooking for relationship patterns in subjects...")
    import re
    for ticket in tickets:
        subject = ticket.get('subject', '')
        ticket_id = str(ticket['id'])
        
        # Look for references to other tickets in this view
        for other_ticket in tickets:
            other_id = str(other_ticket['id'])
            if other_id != ticket_id and other_id in subject:
                logging.info(f"   POTENTIAL RELATIONSHIP: {ticket_id} references {other_id} in subject")
        
        # Look for any ticket-like numbers
        numbers = re.findall(r'\b(\d{6,})\b', subject)
        numbers = [n for n in numbers if n != ticket_id]
        if numbers:
            logging.info(f"   Ticket {ticket_id} subject contains numbers: {numbers}")

if __name__ == "__main__":
    main()
