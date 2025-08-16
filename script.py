import os
import re
import sys
import requests

# Load secrets from environment
ZENDESK_TOKEN = os.getenv("API_TOKEN")
ZENDESK_EMAIL = os.getenv("EMAIL")
ZENDESK_SUBDOMAIN = os.getenv("SUBDOMAIN")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")
SHOPIFY_DOMAIN = os.getenv("SHOPIFY_DOMAIN")

ZENDESK_API = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2"
SHOPIFY_API = f"https://{SHOPIFY_DOMAIN}.myshopify.com/admin/api/2024-01"

def get_ticket_comments(ticket_id):
    url = f"{ZENDESK_API}/tickets/{ticket_id}/comments.json"
    resp = requests.get(url, auth=(f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN))
    resp.raise_for_status()
    return resp.json()["comments"]

def extract_order_and_comment(text):
    """
    Extracts order number like A12345 (or a12345) and the rest of the comment
    """
    match = re.search(r"\b([Aa]\d+)\b\s*(.*)", text)
    if match:
        return match.group(1), match.group(2)
    return None, None

def download_attachment(url, filename):
    """
    Download attachment from Zendesk
    """
    resp = requests.get(url, auth=(f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN), stream=True)
    resp.raise_for_status()
    with open(filename, "wb") as f:
        for chunk in resp.iter_content(1024):
            f.write(chunk)
    return filename

def upload_file_to_shopify(filepath):
    """
    Upload file to Shopify Files API and return URL
    """
    url = f"{SHOPIFY_API}/files.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    filename = os.path.basename(filepath)

    # Encode as base64
    import base64
    with open(filepath, "rb") as f:
        encoded_file = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "file": {
            "attachment": encoded_file,
            "filename": filename
        }
    }

    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()["file"]["url"]

def append_order_note(order_id, note):
    """
    Append a note to Shopify order timeline
    """
    url = f"{SHOPIFY_API}/orders/{order_id}/notes.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
    payload = {"note": note}

    resp = requests.put(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()

def sync_note(ticket_id):
    comments = get_ticket_comments(ticket_id)
    for c in reversed(comments):  # go from latest
        if c["public"] is False:  # internal note
            order_id, comment_text = extract_order_and_comment(c["body"])
            if order_id:
                final_note = f"From Zendesk Ticket {ticket_id}: {comment_text}"

                # Handle attachments
                if c.get("attachments"):
                    file_urls = []
                    for att in c["attachments"]:
                        local_file = download_attachment(att["content_url"], att["file_name"])
                        file_url = upload_file_to_shopify(local_file)
                        file_urls.append(file_url)
                        os.remove(local_file)
                    if file_urls:
                        final_note += "\n\nAttachments:\n" + "\n".join(file_urls)

                # Append to Shopify order timeline
                append_order_note(order_id[1:], final_note)  # strip "A"
                print(f"✅ Synced note & attachments from Zendesk ticket {ticket_id} to Shopify order {order_id}")
                return
    print(f"❌ No valid order pattern like (A12345 comment) found in ticket {ticket_id}")

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "sync_note":
        print("Usage: python script.py sync_note <ticket_id>")
        sys.exit(1)

    ticket_id = sys.argv[2]
    sync_note(ticket_id)
