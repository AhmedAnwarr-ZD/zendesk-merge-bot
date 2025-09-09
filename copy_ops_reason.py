import os
import logging
import requests
import json
import re

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

VIEW_ID = 27529425733661
OPS_ESCALATION_REASON_ID = 20837946693533

def get_json(url):
    """Simple API call"""
    try:
        resp = requests.get(url, auth=AUTH)
        return resp.json() if resp.status_code == 200 else None
    except:
        return None

def find_parent_ticket_id(ticket_id):
    """Try multiple methods to find parent ticket ID"""
    
    print(f"\n=== FINDING PARENT FOR TICKET {ticket_id} ===")
    
    # Method 1: Check ticket via field
    print("Method 1: Checking ticket.via...")
    ticket_data = get_json(f"{BASE_URL}/tickets/{ticket_id}.json")
    if ticket_data:
        via = ticket_data.get('ticket', {}).get('via', {})
        print(f"Via structure: {json.dumps(via, indent=2)}")
        
        # Extract from via.source.from.id if available
        from_obj = via.get('source', {}).get('from', {})
        if from_obj.get('type') == 'ticket' and from_obj.get('id'):
            parent_id = from_obj['id']
            print(f"✅ Found parent {parent_id} in via.source.from.id")
            return parent_id
    
    # Method 2: Check ticket audits for first comment
    print("Method 2: Checking first audit comment...")
    audits_data = get_json(f"{BASE_URL}/tickets/{ticket_id}/audits.json")
    if audits_data:
        audits = audits_data.get('audits', [])
        if audits:
            # Check first audit (creation)
            first_audit = audits[0]
            for event in first_audit.get('events', []):
                if event.get('type') == 'Comment':
                    body = event.get('body', '') + ' ' + event.get('html_body', '')
                    print(f"First comment preview: {body[:200]}")
                    
                    # Look for ticket ID patterns
                    patterns = [
                        rf'https://{SUBDOMAIN}\.zendesk\.com/(?:agent/tickets|hc/en-us/requests)/(\d+)',
                        r'ticket[:\s#]+(\d+)',
                        r'request[:\s#]+(\d+)',
                        r'\b(\d{6,})\b'  # Any 6+ digit number
                    ]
                    
                    for pattern in patterns:
                        matches = re.findall(pattern, body, re.IGNORECASE)
                        for match in matches:
                            potential_parent = int(match)
                            if potential_parent != int(ticket_id):  # Not self
                                print(f"✅ Found potential parent {potential_parent} in first comment")
                                return potential_parent
    
    # Method 3: Check subject for ticket references
    print("Method 3: Checking ticket subject...")
    if ticket_data:
        subject = ticket_data.get('ticket', {}).get('subject', '')
        print(f"Subject: {subject}")
        
        # Look for ticket references in subject
        numbers = re.findall(r'\b(\d{6,})\b', subject)
        for num in numbers:
            if int(num) != int(ticket_id):
                print(f"✅ Found potential parent {num} in subject")
                return int(num)
    
    # Method 4: Search for tickets that might be the parent
    print("Method 4: Reverse search for parent...")
    # Get the requester of this ticket
    if ticket_data:
        requester_id = ticket_data.get('ticket', {}).get('requester_id')
        if requester_id:
            # Search for other tickets from same requester
            search_data = get_json(f"{BASE_URL}/search.json?query=type:ticket requester:{requester_id}")
            if search_data:
                results = search_data.get('results', [])
                print(f"Found {len(results)} tickets from same requester")
                for result in results:
                    result_id = result['id']
                    if result_id != int(ticket_id):
                        # Check if this could be a parent (created before our ticket)
                        result_created = result.get('created_at', '')
                        our_created = ticket_data.get('ticket', {}).get('created_at', '')
                        if result_created < our_created:
                            print(f"✅ Found potential parent {result_id} (created earlier by same requester)")
                            return result_id
    
    print("❌ No parent found")
    return None

def main():
    print("=== SIMPLE PARENT TICKET FINDER ===")
    
    # Get tickets from view
    view_data = get_json(f"{BASE_URL}/views/{VIEW_ID}/tickets.json")
    if not view_data:
        print("Failed to get view data")
        return
    
    tickets = view_data.get('tickets', [])
    print(f"Found {len(tickets)} tickets in view")
    
    # Analyze each ticket for parent relationships
    parent_mapping = {}
    
    for ticket in tickets:
        ticket_id = ticket['id']
        parent_id = find_parent_ticket_id(ticket_id)
        if parent_id:
            parent_mapping[str(ticket_id)] = parent_id
    
    print(f"\n=== RESULTS ===")
    print(f"Found {len(parent_mapping)} parent relationships:")
    for child_id, parent_id in parent_mapping.items():
        print(f"  Child {child_id} → Parent {parent_id}")
    
    # Now test copying the custom field for found relationships
    print(f"\n=== TESTING CUSTOM FIELD COPY ===")
    
    for child_id, parent_id in parent_mapping.items():
        print(f"\nTesting {child_id} → {parent_id}:")
        
        # Get parent ticket
        parent_data = get_json(f"{BASE_URL}/tickets/{parent_id}.json")
        if not parent_data:
            print(f"  ❌ Could not fetch parent ticket {parent_id}")
            continue
        
        # Check for Ops Escalation Reason field
        parent_ticket = parent_data['ticket']
        ops_reason = None
        for field in parent_ticket.get('custom_fields', []):
            if field['id'] == OPS_ESCALATION_REASON_ID:
                ops_reason = field.get('value')
                break
        
        if ops_reason:
            print(f"  ✅ Parent has Ops Escalation Reason: {ops_reason}")
            print(f"  → Would copy to child {child_id}")
        else:
            print(f"  ⚠ Parent {parent_id} has no Ops Escalation Reason value")
    
    if not parent_mapping:
        print("\n❌ NO PARENT RELATIONSHIPS FOUND!")
        print("This suggests the side conversation tickets are not properly linked.")
        print("Please manually check one ticket in Zendesk UI to see how it references the parent.")

if __name__ == "__main__":
    main()
