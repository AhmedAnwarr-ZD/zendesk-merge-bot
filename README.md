# Zendesk User Merge & Identity Normalizer (Windowed)

Advanced Python script to:
- Detect duplicate **end-users** via email/phone
- Merge them intelligently
- Clean up duplicate phone identities

## Problem

- Same customer appears as multiple Zendesk users:
  - Slightly different emails / phones
  - Different channels
- Impacts:
  - Fragmented ticket history
  - Skewed metrics by user
  - Messy phone identities (`+9665…`, `050…`, etc.)

## Solution

A time-windowed script that:

1. Defines a **time window** (default: last 60 minutes) via env:

   - `WINDOW_MINUTES`

2. Finds all **solved tickets** in that window using time-sliced search (adaptive to avoid 422 errors).
3. Collects **requesters** and counts solved tickets per requester.
4. For each requester:
   - Collects identifiers:
     - Normalized email
     - Normalized phone
     - Identities from `/users/{id}/identities`
   - Uses `/users/search?query=<term>` to find other end-users with **exact normalized email/phone**.
   - Builds a **cluster** of matching end-users.

5. For each cluster:
   - Chooses **survivor** using:
     1. Highest **solved ticket count** in window
     2. If tie: `verified == true`
     3. If still tie: **oldest `created_at`**
   - Plans merges: all others → survivor
   - Supports dry run via `DRY_RUN=true`.

6. After merging:
   - Removes duplicate **phone identities** with same normalized number, keeping primary where possible.

## Tech Stack

- Python 3
- `requests`
- Zendesk Search, Users, Identities APIs

## Configuration

Env vars:

- `SUBDOMAIN`
- `EMAIL`
- `API_TOKEN`
- Optional:
  - `DRY_RUN` (`true` / `false`)
  - `WINDOW_MINUTES`
  - `MAX_MERGES`
  - `CHUNK_MINUTES`, `MIN_CHUNK_MINUTES`
  - `CLEAN_DUPLICATE_IDENTITIES`

## Business Impact (Estimate)

- Gradually **defragments the user base** with minimal risk
- Improves per-customer analytics & CSAT attribution
- Reduces manual user merge work for admins

## My Role

I designed the survivor selection logic, time-windowed scanning, and identity cleanup, then implemented the script with robust retry logic and detailed logging.
