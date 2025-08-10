import time
import requests
from urllib.parse import urlencode

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ahead/zendesk-merge-bot", "Accept": "application/json"})

def _sleep_from_headers(resp, default=5):
    ra = resp.headers.get("Retry-After")
    if ra and ra.isdigit():
        time.sleep(int(ra))
        return
    reset = resp.headers.get("ratelimit-reset")  # some endpoints use this
    if reset:
        # reset is an absolute epoch time in some APIs; fall back to default if parse fails
        try:
            wait = max(0, int(reset) - int(time.time()))
            time.sleep(wait or default)
            return
        except Exception:
            pass
    time.sleep(default)

def _request(method, url, **kw):
    while True:
        resp = SESSION.request(method, url, auth=AUTH, timeout=30, **kw)
        if resp.status_code in (429, 503):
            _sleep_from_headers(resp, default=5)
            continue
        resp.raise_for_status()
        return resp

def get_pages(url, per_page_pause_sec=7):  # ≤ ~8–9 calls/min for incremental exports
    while url:
        resp = _request("GET", url)
        data = resp.json()
        yield data
        url = data.get("next_page")
        if url:
            time.sleep(per_page_pause_sec)  # keep under incremental rate limit

def update_many_status(ids, status):
    # batch by 100
    for i in range(0, len(ids), 100):
        batch = ids[i:i+100]
        q = urlencode({"ids": ",".join(map(str, batch))})
        _request("PUT", f"{BASE_URL}/tickets/update_many.json?{q}",
                 json={"ticket": {"status": status}})

def get_all_side_convo_tickets():
    tickets, now = [], datetime.utcnow()
    start_time = int((now - timedelta(days=1)).timestamp())
    url = f"{BASE_URL}/incremental/tickets.json?start_time={start_time}"
    for data in get_pages(url):
        side_convo_tickets = [
            t for t in data.get("tickets", [])
            if t.get("via", {}).get("channel") == "side_conversation"
            and t.get("status") in ("new", "open", "pending", "solved")  # include solved for reopen/solve flow
            and datetime.strptime(t["updated_at"], "%Y-%m-%dT%H:%M:%SZ") >= now - timedelta(days=1)
        ]
        tickets.extend(side_convo_tickets)
        log(f"Fetched {len(side_convo_tickets)} (Total: {len(tickets)})")
    log(f"Total in last 24h: {len(tickets)}")
    return tickets

def add_private_note_to_ticket(ticket_id, note):
    _request("PUT", f"{BASE_URL}/tickets/{ticket_id}.json",
             json={"ticket": {"comment": {"body": note, "public": False}}})

def reopen_ticket(ticket_id):
    _request("PUT", f"{BASE_URL}/tickets/{ticket_id}.json", json={"ticket": {"status": "open"}})

def merge_child_tickets():
    tickets = get_all_side_convo_tickets()
    grouped = defaultdict(list)
    for t in tickets:
        grouped[t["subject"]].append(t)

    for subject, ticket_list in grouped.items():
        if len(ticket_list) < 2:
            continue
        ticket_list.sort(key=lambda x: x["created_at"])
        main_ticket, duplicates = ticket_list[0], ticket_list[1:]
        log(f"Merging {len(duplicates)} into main {main_ticket['id']} for subject: {subject}")

        # Reopen solved dups in one batch (if any), then immediately re-solve all in one batch
        solved_dup_ids = [d["id"] for d in duplicates if d["status"] == "solved"]
        if solved_dup_ids:
            update_many_status(solved_dup_ids, "open")

        # Single comment on the main ticket (kept as single PUT; update_many doesn't do comments)
        note_lines = [f"Merged from ticket {d['id']}:\n\n{d.get('description','')}" for d in duplicates]
        add_private_note_to_ticket(main_ticket["id"], "\n\n---\n\n".join(note_lines))

        # Solve all dups in batches
        update_many_status([d["id"] for d in duplicates], "solved")
