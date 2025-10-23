import os
import time
import json
import logging
import requests
from time import sleep
from datetime import datetime, timezone
from collections import defaultdict
from urllib.parse import urlencode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ========= Config via env =========
SUBDOMAIN_RAW = os.environ["SUBDOMAIN"].strip()
EMAIL = os.environ["EMAIL"].strip()
API_TOKEN = os.environ["API_TOKEN"].strip()

# Optional tuning
PER_PAGE = int(os.getenv("PER_PAGE", "1000"))                 # time-based export page size
INCLUDE_SINCE_EPOCH = int(os.getenv("INCLUDE_SINCE_EPOCH", "0"))  # 0 = full history
MERGE_DELAY_SEC = float(os.getenv("MERGE_DELAY_SEC", "0.25")) # tiny delay for rate limits
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"      # default preview
MAX_MERGES = int(os.getenv("MAX_MERGES", "500"))              # safety cap
PREFER_VERIFIED_EMAIL = os.getenv("PREFER_VERIFIED_EMAIL", "true").lower() == "true"
SKIP_SUSPENDED = os.getenv("SKIP_SUSPENDED", "false").lower() == "true"
LOG_PREVIEW = os.getenv("LOG_PREVIEW", "true").lower() == "true"

RETRY_MAX = int(os.getenv("RETRY_MAX", "5"))
RETRY_BASE_DELAY = float(os.getenv("RETRY_BASE_DELAY", "0.8"))

def _sanitize_host(value: str) -> str:
    """
    Accepts either:
      - bare subdomain: 'acme'
      - zendesk host: 'acme.zendesk.com'
      - URL: 'https://acme.zendesk.com' or 'http://support.acme.com'
      - custom host: 'support.acme.com'
    Returns a host like 'acme.zendesk.com' or 'support.acme.com'.
    """
    v = value.strip().lower()
    if v.startswith("http://") or v.startswith("https://"):
        v = v.split("://", 1)[1]
    v = v.split("/", 1)[0]
    if not v:
        raise SystemExit("SUBDOMAIN is empty. Set it to your Zendesk subdomain (e.g., 'aleena').")
    if "." in v:
        return v
    return f"{v}.zendesk.com"

HOST = _sanitize_host(SUBDOMAIN_RAW)
BASE = f"https://{HOST}"

SESSION = requests.Session()
SESSION.auth = (f"{EMAIL}/token", API_TOKEN)
SESSION.headers.update({"Content-Type": "application/json", "Accept": "application/json"})

# ========= HTTP helpers with retries =========
def _request_with_retries(method, url, **kwargs):
    for attempt in range(1, RETRY_MAX + 1):
        r = SESSION.request(method, url, timeout=30, **kwargs)
        if r.status_code < 400:
            return r
        if r.status_code in (429, 500, 502, 503, 504):
            wait = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logging.warning(f"{method} {url} -> {r.status_code}; retry {attempt}/{RETRY_MAX} in {wait:.1f}s")
            sleep(wait)
            continue
        # hard error (4xx other than 429)
        return r
    return r  # last response

def zget(url, params=None):
    if params:
        url = f"{url}?{urlencode(params)}"
    r = _request_with_retries("GET", url)
    if r.status_code != 200:
        raise Exception(f"GET {url} -> {r.status_code}: {r.text}")
    return r.json()

def zput(url, payload):
    return _request_with_retries("PUT", url, json=payload)

# ========= Normalizers & utils =========
def norm_email(e):
    if not e:
        return None
    return e.strip().lower()

def norm_phone(p):
    if not p:
        return None
    s = "".join(ch for ch in p if ch.isdigit() or ch == "+")
    # normalize common patterns
    if s.startswith("00"):
        s = "+" + s[2:]
    if not s.startswith("+") and s.isdigit():
        # heuristic: if KSA local (e.g., 05xxxxxxxx), turn to +9665xxxxxxxx
        if s.startswith("0") and len(s) in (9, 10):
            s = "+966" + s[1:]
    return s

def parse_dt(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return datetime(2100, 1, 1, tzinfo=timezone.utc)

def role_is_end_user(user):
    return (user.get("role") or "").lower() == "end-user"

def pick_survivor(users):
    """
    Choose the surviving user:
    1) any verified profile (if flag on)
    2) earliest created_at
    """
    candidates = users
    if PREFER_VERIFIED_EMAIL:
        verified = [u for u in users if u.get("verified")]
        if verified:
            candidates = verified
    return sorted(candidates, key=lambda u: parse_dt(u.get("created_at") or ""))[0]

# ========= Preflight =========
def preflight():
    """Fail fast if host/creds are wrong; also logs which host we're hitting."""
    try:
        r = SESSION.get(f"{BASE}/api/v2/account.json", timeout=20)
        if r.status_code != 200:
            raise Exception(f"Preflight failed {r.status_code}: {r.text}")
        logging.info(f"Connected to Zendesk host: {HOST}")
    except requests.exceptions.RequestException as e:
        raise SystemExit(f"Preflight connection error to {BASE}: {e}")

# ========= Incremental export =========
def incremental_users(start_time):
    """
    Iterate users using cursor-based export when start_time > 0; otherwise use time-based export for full history.
    """
    if start_time and start_time > 0:
        # Cursor-based: do NOT send per_page; use cursor token
        url = f"{BASE}/api/v2/incremental/users/cursor"
        params = {"start_time": max(start_time, int(time.time()) - 120)}
        while True:
            resp = zget(url, params)
            for u in resp.get("users", []):
                yield u
            if resp.get("end_of_stream"):
                break
            after = resp.get("after_cursor")
            if not after:
                break
            url = f"{BASE}/api/v2/incremental/users/cursor"
            params = {"cursor": after}
    else:
        # Time-based for full history; supports per_page
        url = f"{BASE}/api/v2/incremental/users.json"
        params = {"start_time": 0, "per_page": PER_PAGE}
        while True:
            resp = zget(url, params)
            for u in resp.get("users", []):
                yield u
            next_page = resp.get("next_page")
            if not next_page:
                break
            url, params = next_page, None

# ========= Merge operation =========
def merge_user(source_id, target_id):
    """
    Merge source end-user INTO target end-user.
    PUT /api/v2/users/{source_id}/merge
    Body: {"user": {"id": target_id}}
    """
    url = f"{BASE}/api/v2/users/{source_id}/merge"
    payload = {"user": {"id": target_id}}
    if DRY_RUN:
        logging.info(f"[DRY-RUN] would merge source {source_id} -> target {target_id}")
        return True
    resp = zput(url, payload)
    if resp.status_code in (200, 201, 202, 204):
        logging.info(f"✅ merged {source_id} → {target_id}")
        return True
    logging.error(f"❌ merge failed {source_id} → {target_id} :: {resp.status_code} {resp.text}")
    return False

# ========= Main =========
def main():
    preflight()
    logging.info("Scanning users…")
    by_email = defaultdict(list)
    by_phone = defaultdict(list)

    count = 0
    for user in incremental_users(INCLUDE_SINCE_EPOCH):
        count += 1
        if not role_is_end_user(user):
            continue
        if SKIP_SUSPENDED and user.get("suspended"):
            continue

        e = norm_email(user.get("email"))
        p = norm_phone(user.get("phone"))

        if e:
            by_email[e].append(user)
        if p:
            by_phone[p].append(user)

        if count % 5000 == 0:
            logging.info(f"… processed {count} users")

    logging.info(f"Indexed end-users: emails={len(by_email)}, phones={len(by_phone)}")

    planned_merges = []  # (source_id, target_id, reason, key)

    # 1) email-based merges
    for email, users in by_email.items():
        if len(users) < 2:
            continue
        survivor = pick_survivor(users)
        s_id = survivor["id"]
        if LOG_PREVIEW:
            logging.info(f"[cluster-email] {email}: {len(users)} users -> survivor {s_id}")
        for u in users:
            if u["id"] == s_id:
                continue
            planned_merges.append((u["id"], s_id, "email", email))

    # 2) phone-based merges (skip pairs already covered by email)
    already = set((src, tgt) for (src, tgt, _, _) in planned_merges)
    for phone, users in by_phone.items():
        if len(users) < 2:
            continue
        survivor = pick_survivor(users)
        s_id = survivor["id"]
        if LOG_PREVIEW:
            logging.info(f"[cluster-phone] {phone}: {len(users)} users -> survivor {s_id}")
        for u in users:
            if u["id"] == s_id:
                continue
            pair = (u["id"], s_id)
            if pair not in already:
                planned_merges.append((u["id"], s_id, "phone", phone))

    # Dedup “source -> target” operations
    unique_merges = {}
    for src, tgt, reason, key in planned_merges:
        unique_merges[(src, tgt)] = (reason, key)
    planned_merges = [(src, tgt, r, k) for (src, tgt), (r, k) in unique_merges.items()]

    logging.info(f"Planned merges: {len(planned_merges)} (cap={MAX_MERGES}, dry_run={DRY_RUN})")

    merged = 0
    for src, tgt, reason, key in planned_merges[:MAX_MERGES]:
        logging.info(f"→ merge by {reason}: {key} | {src} → {tgt}")
        ok = merge_user(src, tgt)
        if ok:
            merged += 1
            time.sleep(MERGE_DELAY_SEC)

    logging.info(f"Done. Total merged: {merged} (dry_run={DRY_RUN})")

if __name__ == "__main__":
    main()
