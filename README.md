# Zendesk Automation Suite  
### (Parent–Child Ops Reason Copier + Duplicate Ticket Merge Bot)

This repository contains two production-ready Python automation scripts designed for Zendesk environments with high ticket volume, complex Ops workflows, and the need for strict data hygiene:

1. **Ops Reason Parent–Child Copier**  
   Automatically detects side-conversation child tickets, copies the parent ticket's *Ops Escalation Reason* into the child, and handles missing-field cases intelligently.  
   :contentReference[oaicite:0]{index=0}

2. **Duplicate Ticket Merge Bot**  
   Identifies duplicate tickets using requester, subject, and channel logic (with exclusions) and merges them into the correct parent ticket.  
   :contentReference[oaicite:1]{index=1}

Together, these two scripts reduce manual Ops overhead, ensure consistency across escalations, and maintain a clean Zendesk ticket database.

---

# 1. Parent–Child Ops Escalation Reason Copier  
*(copy_ops_reason.py)*

### 🔍 What it does  
This script scans a specific Zendesk View that contains *side conversation child tickets*. For each child ticket, it:

- Identifies the correct **parent ticket** using `external_id`  
- Pulls the **Ops Escalation Reason** field from the parent  
- Copies the field to the child  
- If the parent does **not** have Ops Escalation Reason:
  - Adds an **internal note** to the parent with requester + assignee details  
- Generates a final summary log of all actions

### 🧠 Key Features  
- Reliable detection of parent ticket IDs from side conversation metadata  
- Smart caching for:
  - Parent tickets  
  - User records  
- Rate-limit aware (handles Zendesk 429 gracefully)  
- Retries + backoff logic  
- Clean logging with clear success/error counts  
- Zero duplicated API calls unless necessary  

### ⚙️ Required Environment Variables  
| Variable | Description |
|---------|-------------|
| `SUBDOMAIN` | Your Zendesk subdomain |
| `EMAIL` | API user email |
| `API_TOKEN` | Zendesk API Token |

### 🧩 Important Constants  
| Constant | Purpose |
|---------|----------|
| `OPS_ESCALATION_REASON_ID` | Custom field ID to sync from parent to child |
| `VIEW_ID` | Zendesk view containing side-conversation child tickets |

---

# 2. Duplicate Ticket Merge Bot  
*(merge_bot.py)*

### 🔍 What it does  
This script automatically finds and merges duplicate tickets based on strict grouping logic:

Duplicate grouping includes:
- Same requester  
- Same subject  
- Same channel  
- (Special handling for **side_conversation** tickets)

### 🚫 Exclusions  
- Tickets from specific organization domains  
  - e.g., government emails: `moc.gov.sa`
- Channels you don’t want merged  
  - `whatsapp`  
  - `any_channel`  
- Tickets with closed/archived target parents  

### 🧠 Smart Behaviors  
- Uses `created_at` timestamp to pick the oldest ticket as the merge target  
- Avoids merging **into** a closed/archived ticket  
- Fully logs every merge, including “none merged” scenarios  
- Simple and safe merge endpoint (`/merge.json`)

### 🧩 Required Environment Variables  
Same variables as script #1.

---

# 🔧 Installation

Clone the repo and install requirements:

```bash
git clone <your-repo>
cd <your-repo>
pip install -r requirements.txt
