# -----------------------------------
# Zendesk helper: fetch agent name
# -----------------------------------
def get_agent_name(agent_id):
    url = f"https://shopaleena.zendesk.com/api/v2/users/{agent_id}.json"
    auth = (f"{EMAIL}/token", API_TOKEN)
    resp = requests.get(url, auth=auth)
    resp.raise_for_status()
    user = resp.json().get("user", {})
    first_name = user.get("name", "").split()[0] if user.get("name") else "Unknown"
    last_name = user.get("name", "").split()[-1] if len(user.get("name", "").split()) > 1 else ""
    last_initial = last_name[0] if last_name else ""
    return f"{first_name} {last_initial}"

# -----------------------------------
# Updated sync_note function
# -----------------------------------
def sync_note(ticket_id):
    print(f"Debug: syncing ticket_id={ticket_id}")

    # fetch latest private note
    note_text, agent_id = get_latest_private_note(ticket_id)
    if not note_text:
        raise Exception("No private note found in Zendesk.")

    ts_date = datetime.now().strftime("%Y-%m-%d")

    # extract order name
    match = re.search(r"([A-Z0-9]+)", note_text)
    if not match:
        raise Exception("Could not detect order number in note text.")
    
    order_name = match.group(1).strip()

    # convert agent_id to agent name
    agent_name = get_agent_name(agent_id)

    # build message block
    message_block = f"#{ticket_id} | {agent_name} | {ts_date}\n\n{note_text}"

    print(f"Debug: order_name={order_name}, agent={agent_name}, ts_date={ts_date}")
    print("Debug: message_block:")
    print(message_block)

    # Shopify order search
    url = f"https://{SHOPIFY_DOMAIN}/admin/api/2023-10/orders.json"
    headers = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}
    params = {
        "query": f"name:{order_name}",
        "status": "any"
    }

    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    orders = resp.json().get("orders", [])

    if not orders:
        raise Exception(f"No Shopify order found for {order_name}")

    shop_order = orders[0]

    # update Shopify note
    shopify_update_order_note(shop_order["id"], message_block)
