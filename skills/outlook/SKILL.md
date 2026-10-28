---
name: outlook
description: >-
  Inspects, searches, synchronizes, and summarizes Outlook Web (outlook.office.com, outlook.live.com)
  emails, meeting invites, and action items. Uses local SQLite storage and updates the master
  activity digest. Trigger when the user asks about Outlook emails, unread mail, meeting requests,
  corporate announcements, or when invoked by scheduled tasks.
---

# Outlook Skill

Manages Outlook Web email ingestion, SQLite querying, and continuous maintenance of the activity digest.

## Core Responsibilities

1. **Querying Emails**: Look up historical emails, announcements, and meeting notes using full-text search (FTS5).
2. **Periodic Synchronization**: Pull new messages from active Outlook Web browser tabs via the local browser bridge (`browserctl`) into SQLite (`outlook.db`).
3. **Master Summary Maintenance**: Synthesize raw emails across threads into the unified executive summary in `SUMMARY.md`.
4. **Chat Reporting**: When invoked on a schedule or by the user, report only the latest delta/changes directly in chat.

---

## Tool Reference

The CLI utility lives at `skills/outlook/scripts/outlook_tool.py`:

```bash
# Locate repository root
REPO_ROOT=$(git rev-parse --show-toplevel)
OUTLOOK_TOOL="$REPO_ROOT/skills/outlook/scripts/outlook_tool.py"

# 1. View recent emails and unread status
python3 "$OUTLOOK_TOOL" list --limit 30
python3 "$OUTLOOK_TOOL" list --unread

# 2. Inspect raw email body or thread
python3 "$OUTLOOK_TOOL" read --id "<email_id_or_keyword>"

# 3. Search emails using full-text index
python3 "$OUTLOOK_TOOL" search "<query>"

# 4. View pending unreviewed emails
python3 "$OUTLOOK_TOOL" pending

# 5. Synchronize messages from active Outlook Web tab
python3 "$OUTLOOK_TOOL" sync

# 6. Mark emails as reviewed after updating the summary
python3 "$OUTLOOK_TOOL" ack --all
# or acknowledge specific IDs
python3 "$OUTLOOK_TOOL" ack --ids <id1> <id2>
```

---

## Ingestion Architecture

1. **Local Browser Bridge Ingestion**:
   - `outlook_tool.py` connects via `browserctl` to the active `outlook.office.com` or `outlook.live.com` tab.
   - Extracts email metadata (sender, subject, timestamp, snippet, unread flag) directly from tab state.
2. **FTS5 Full-Text Indexing**:
   - Stores emails in local SQLite with an FTS5 virtual table for instant full-text searching across subject, snippet, and body.
3. **Delta Deduplication**:
   - Uses conversation ID / email ID to update existing records idempotently.

---

## Workflow: Scheduled Digest Update

When invoked on a schedule or asked to check Outlook updates:

1. **Fetch & Check Pending**:
   - Run `python3 "$OUTLOOK_TOOL" pending` (optionally preceded by `sync`).
   - If there are zero pending emails, report: "No new Outlook emails since last check."

2. **Analyze Emails**:
   - Group pending emails by topic or sender.
   - Identify:
     - Urgent action items and deadlines.
     - Meeting invitations or schedule changes.
     - Key project announcements.

3. **Update Master Digest In-Place**:
   - Update or append the specific topic under `SUMMARY.md`.
   - Update the decisions and action items checklist.
   - Save the file in-place.

4. **Acknowledge Processed Messages**:
   - Run `python3 "$OUTLOOK_TOOL" ack --all`.

5. **Surface Delta to Chat**:
   - Output a concise summary of active discussions and pending actions in chat.
