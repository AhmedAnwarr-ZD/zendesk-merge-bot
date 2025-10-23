import os
import sys
import json
import time
import logging
import requests
from time import sleep
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

# ---------- logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---------- env (keep your names) ----------
SUBDOMAIN_RAW = os.environ["SUBDOMAIN"].strip()
EMAIL = os.environ["EMAIL"].strip()
API_TOKEN = os.environ["API_TOKEN"].strip()

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
WINDOW_MINUTES = int(os.getenv("WINDOW_MINUTES", "60"))
MAX_MERGES = int(os.getenv("MAX_MERGES", "50"))

RETRY_MAX = int(os.getenv("RETRY_MAX", "5"))
RETRY_BASE_DELAY = float(os.getenv("RETRY_BASE_DELAY", "0.8"))
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "100"))
MERGE_DELAY_SEC = float(os.getenv("MERGE_DELAY_SEC", "0.25"))

# ---------- helpers ----------
def _sanitize_host(value: str) -> str:
    v = value.lower().strip()
    if v.startswith("http://") or v.startswith("https://"):
        v = v.split("://", 1)[1]
    v = v.split("/", 1)[0]
    if not v:
        raise SystemExit("SUBDOMAIN is empty.")
    if "." in v:
        return v
    return f"{v}.zendesk.com"

HOST = _sanitize_host(SUBDOMAIN_RAW)
BASE = f"https://{HOST}"

SESSION = requests.Session()
SESSION.auth = (f"{EMAIL}/token", API_TOKEN)
SESSION.headers.update({"Content-Type": "application/json", "Accept": "application/json"})

def _request_with_retries(method, url, **kwargs):
    for attempt in range(1, RETRY_MAX + 1):
        r = SESSION.request(method, url, timeout=30, **kwargs)
        if r.status_code < 400:
            return r
        if r.status_code in (429, 500, 502, 503, 504):
            retry_after = r.headers.get("Retry-After")
            if retry_after:
                try:
                    wait = float(retry_after)
                except ValueError:
                    wait = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            else:
                wait = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logging.warning(f"{method} {url} -> {r.status_code}; retry {attempt}/{RETRY_MAX} in {wait:.1f}s")
            sleep(wait)
            continue
        # hard 4xx
        return r
    return r

def zget(path_or_full, params=None):
    url = path_or_full if path_or_full.startswith("http") else f"{BASE}{path_or_full}"
    if params:
        url = f"{url}?{urlencode(params)}"
    r = _request_with_retries("GET", url)
    if r.status_code != 200:
        raise Exception(f"GET {url} -> {r.status_code}: {r.text}")
    return r.json()

def zput(path, payload):
    url = f"{BASE}{path}"
    return _request_with_retries("PUT", url, json=payload)

def preflight():
    r = _request_with_retries("GET", f"{BASE}/api/v2/account.json")
    if r.status_code != 200:
        raise SystemExit(f"Preflight failed {r.status_code}: {r.text}")
    logging.info(f"Connected to Zendesk host: {HOST}")

def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def norm_email(e: str | None) -> str | None:
    return e.strip().lower() if e else None

def norm_phone(p: str | None) -> str | None:
    if not p: return None
    s = "".join(ch for ch in p if ch.isdigit() or ch == "+")
    if s.startswith("00"):
        s = "+" + s[2:]
    if not s.startswith("+") and s.isdigit():
        # simple KSA heuristic; duplicates still match exact strings
        if s.startswith("0") and len(s) in (9, 10):
            s = "+966" + s[1:]
    return s

# ---------- API bits ----------
def search_solved_tickets_since(since_iso: str):
    """
    Fetch tickets solved after since_iso (UTC).
    """
    q = f'type:ticket status:solved solved>{since_iso}'
    params = {"query": q, "per_page": PAGE_SIZE}
    url = "/api/v2/search.json"
    while True:
        resp = zget(url, params)
        for t in resp.get("results", []):
            yield t
        next_page = resp.get("next_page")
        if not next_page:
            break
        # next_page is absolute
        url, params = next_page, None
        sleep(0.2)

def users_show_many(ids: list[int]) -> list[dict]:
    users = []
    for i in range(0, len(ids), 100):
        chunk = ids[i:i+100]
        resp = zget("/api/v2/users/show_many.json", {"ids": ",".join(map(str, chunk))})
        users.extend(resp.get("users", []))
        sleep(0.2)
    return users

def requester_identities(user_id: int) -> list[dict]:
    """
    Fetch identities for the requester only (emails/phones), optional but cheap.
    """
    try:
        resp = zget(f"/api/v2/users/{user_id}/identities.json")
        return resp.get("identities", [])
    except Exception as e:
        logging.warning(f"identities fetch failed for {user_id}: {e}")
        return []

def search_users_by_term(term: str) -> list[dict]:
    """
    Zendesk Users Search. We pass the raw term (email or phone).
    We'll filter exact matches after normalization.
    """
    # users search endpoint:
    resp = zget("/api/v2/users/search.json", {"query": term})
    return resp.get("users", [])

def merge_user(source_id: int, target_id: int) -> bool:
    if DRY_RUN:
        logging.info(f"[DRY-RUN] would merge {source_id} -> {target_id}")
        return True
    r = zput(f"/api/v2/users/{source_id}/merge", {"user": {"id": target_id}})
    if r.status_code in (200, 201, 202, 204):
        logging.info(f"✅ merged {source_id} → {target_id}")
        return True
    logging.error(f"❌ merge failed {source_id} → {target_id} :: {r.status_code} {r.text}")
    return False

# ---------- merge logic ----------
def main():
    preflight()

    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=WINDOW_MINUTES)
    since_iso = iso_utc(start)
    logging.info(f"Window: {since_iso} → {iso_utc(end)} (UTC)")

    # 1) solved tickets → requesters + counts
    requester_counts: dict[int, int] = {}
    requester_ids: set[int] = set()

    for t in search_solved_tickets_since(since_iso):
        rid = t.get("requester_id")
        if not rid: 
            continue
        requester_ids.add(rid)
        requester_counts[rid] = requester_counts.get(rid, 0) + 1

    if not requester_ids:
        logging.info("No solved tickets in this window. Nothing to do.")
        return

    logging.info(f"Unique requesters in window: {len(requester_ids)}")

    # 2) fetch requesters
    requesters = users_show_many(list(requester_ids))
    req_by_id = {u["id"]: u for u in requesters}

    planned = []  # (src, tgt, reason, key)

    def pick_survivor(candidates: list[dict]) -> int:
        """
        Winner: highest solved-count in window; tie -> verified; next tie -> oldest created_at.
        """
        def created_ts(u):
            try:
                dt = datetime.fromisoformat(u.get("created_at","").replace("Z","+00:00"))
                return dt.timestamp()
            except Exception:
                return float("inf")
        return max(
            candidates,
            key=lambda u: (
                requester_counts.get(u["id"], 0),
                1 if u.get("verified") else 0,
                -created_ts(u)  # older first
            )
        )["id"]

    # 3) for each requester, look outward (users search) by email/phone
    for rid in requester_ids:
        ruser = req_by_id.get(rid)
        if not ruser or (ruser.get("role","").lower() != "end-user"):
            continue

        # identifiers: primary + identities (requester only)
        emails = set()
        phones = set()

        e = norm_email(ruser.get("email"))
        p = norm_phone(ruser.get("phone"))
        if e: emails.add(e)
        if p: phones.add(p)

        for ident in requester_identities(rid):
            if ident.get("type") == "email":
                ee = norm_email(ident.get("value"))
                if ee: emails.add(ee)
            elif ident.get("type") in ("phone_number", "phone"):
                pp = norm_phone(ident.get("value"))
                if pp: phones.add(pp)

        # search by each identifier; cluster matches (end-users only)
        cluster_ids = set([rid])

        # email matches
        for ee in emails:
            matches = search_users_by_term(ee)
            for u in matches:
                if (u.get("role","").lower() == "end-user"):
                    if norm_email(u.get("email")) == ee:
                        cluster_ids.add(u["id"])

        # phone matches
        for pp in phones:
            if not pp:
                continue
            matches = search_users_by_term(pp)
            for u in matches:
                if (u.get("role","").lower() == "end-user"):
                    if norm_phone(u.get("phone")) == pp:
                        cluster_ids.add(u["id"])

        if len(cluster_ids) <= 1:
            continue

        # Fetch full user objects for cluster members (ensure we have data for non-requesters)
        missing = [uid for uid in cluster_ids if uid not in req_by_id]
        if missing:
            fetched = users_show_many(missing)
            for u in fetched:
                req_by_id[u["id"]] = u

        cluster_users = [req_by_id[uid] for uid in cluster_ids if uid in req_by_id]
        survivor = pick_survivor(cluster_users)

        for uid in cluster_ids:
            if uid == survivor:
                continue
            planned.append((uid, survivor, "email/phone", "cluster"))

    if not planned:
        logging.info("No duplicates detected across the userbase for this window.")
        return

    # dedupe pairs
    uniq = {}
    for src, tgt, reason, key in planned:
        uniq[(src, tgt)] = (reason, key)
    planned = [(s, t, r, k) for (s, t), (r, k) in uniq.items()]

    logging.info(f"Planned merges: {len(planned)} (cap={MAX_MERGES}, dry_run={DRY_RUN})")
    merged = 0
    for src, tgt, reason, key in planned[:MAX_MERGES]:
        logging.info(f"→ merge by {reason}: {key} | {src} → {tgt} | solved[src]={requester_counts.get(src,0)} solved[tgt]={requester_counts.get(tgt,0)}")
        if merge_user(src, tgt):
            merged += 1
            sleep(MERGE_DELAY_SEC)

    logging.info(f"Done. Merged this run: {merged} (dry_run={DRY_RUN})")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.error(str(e))
        sys.exit(1)
