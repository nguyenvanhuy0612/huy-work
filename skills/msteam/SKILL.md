---
name: msteam
description: >-
  Inspects, searches, synchronizes, and summarizes Microsoft Teams discussions, agreements,
  and action items across all channels. Uses the local SQLite database and updates the master
  activity digest. Trigger when the user asks about Teams messages, unread chats, project
  discussions, recent decisions, or when invoked by scheduled tasks.
---

# Microsoft Teams Skill

Manages Microsoft Teams message ingestion, SQLite querying, and continuous maintenance of the activity digest.

## Core Responsibilities

1. **Querying Discussions**: Look up historical discussions, decisions, and messages using full-text search (FTS5) or structured channel queries.
2. **Periodic Synchronization**: Pull new messages from active Teams browser tabs via the local browser bridge into SQLite (`msteam.db`).
3. **Master Summary Maintenance**: Synthesize raw messages across workspace chats into the unified executive summary in `SUMMARY.md`.
4. **Chat Reporting**: When invoked on a schedule or by the user, report only the latest delta/changes directly in chat.

---

## Tool Reference

The CLI utility lives at `skills/msteam/scripts/msteam_tool.py`:

```bash
# Locate repository root
REPO_ROOT=$(git rev-parse --show-toplevel)
MSTEAM_TOOL="$REPO_ROOT/skills/msteam/scripts/msteam_tool.py"

# 1. View all active channels, types (personal, direct, group, channel), and unreviewed counts
python3 "$MSTEAM_TOOL" chats

# 2. Inspect raw chat logs
python3 "$MSTEAM_TOOL" log --chat "<chat_title_or_id>" --limit 20

# 3. Search messages using full-text index
python3 "$MSTEAM_TOOL" search "<query>"

# 4. View pending unreviewed messages
python3 "$MSTEAM_TOOL" pending

# 5. Synchronize messages from Teams (Token Harvester Pattern)
# Harvests credentials once (~80ms) and pulls data via direct Python network calls
python3 "$MSTEAM_TOOL" sync

# Target a specific chat (e.g. 1:1 direct chat, personal notes, or team group)
python3 "$MSTEAM_TOOL" sync --chat "48:notes"
python3 "$MSTEAM_TOOL" sync --chat "Team Lead" --max-pages 2

# 6. Mark messages as reviewed after updating the summary
python3 "$MSTEAM_TOOL" ack --all
# or acknowledge specific IDs
python3 "$MSTEAM_TOOL" ack --ids <id1> <id2>
```

---

## Ingestion Architecture: Token Harvester & Early-Break Delta Sync

1. **One-Time Token Harvest**:
   - `msteam_tool.py sync` queries the active Teams tab using `authService.acquireToken('https://ic3.teams.office.com')`.
   - The token is cached in Python memory (45 min TTL), immediately releasing the browser bridge to avoid UI locking.
2. **Direct Out-of-Browser Fetching**:
   - Python requests ChatSvc endpoints natively with `Authorization: Bearer <token>`.
3. **Early-Break Delta Sync**:
   - Compares incoming messages (ordered newest first) against the latest local message timestamp ($T_A$).
   - Aborts pagination immediately upon reaching existing records, completing incremental updates in exactly 1 HTTP request per chat.
4. **Deterministic Chat Typing**:
   - `48:notes` -> `personal`
   - `19:...@unq.gbl.spaces` -> `direct`
   - `19:...@thread.v2` -> `group`
   - `19:...@thread.tacv2` -> `channel`

---

## Workflow: Scheduled Digest Update

When invoked on a schedule or asked to check Teams updates:

1. **Fetch & Check Pending**:
   - Run `python3 "$MSTEAM_TOOL" pending` (optionally preceded by `sync`).
   - If there are zero pending messages, report: "No new Microsoft Teams messages since last check."

2. **Analyze Discussions**:
   - Group pending messages by chat and conversation thread.
   - For each conversation, identify:
     - The topic under discussion.
     - Differing viewpoints, arguments, or options proposed.
     - Final agreements or consensus reached (`Resolved`, `Pending Approval`).
     - Open questions, blockers, or assigned action items.

3. **Update Master Digest In-Place**:
   - Update or append the specific topic under `SUMMARY.md`.
   - Update the decisions and action items checklist.
   - Save the file in-place.

4. **Acknowledge Processed Messages**:
   - Run `python3 "$MSTEAM_TOOL" ack --all`.

5. **Surface Delta to Chat**:
   - Output a concise update directly in the chat session:
     - Which channels had new activity.
     - Bullet points summarizing what was discussed, what was agreed upon, and what is next.
