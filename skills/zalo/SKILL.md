---
name: zalo
description: >-
  Inspects, searches, synchronizes, and summarizes Zalo Web (chat.zalo.me) discussions, agreements,
  and action items across all direct and group chats. Uses the local SQLite database and updates
  the master activity digest. Trigger when the user asks about Zalo messages, unread chats,
  client communications, or when invoked by scheduled tasks.
---

# Zalo Skill

Manages Zalo Web message ingestion, SQLite querying, and maintenance of the master activity digest.

## Core Responsibilities

1. **Querying Discussions**: Search historical conversations, decisions, and messages using full-text search (FTS5).
2. **Periodic Synchronization**: Pull new messages from active Zalo Web browser tabs via the local browser bridge (`browserctl`) into SQLite (`zalo.db`).
3. **Master Summary Maintenance**: Synthesize raw messages into the unified executive summary in `SUMMARY.md`.
4. **Chat Reporting**: When invoked on a schedule or by the user, report only the latest delta/changes directly in chat.

---

## Tool Reference

The CLI utility lives at `skills/zalo/scripts/zalo_tool.py`:

```bash
# Locate repository root
REPO_ROOT=$(git rev-parse --show-toplevel)
ZALO_TOOL="$REPO_ROOT/skills/zalo/scripts/zalo_tool.py"

# 1. View all active chats, types (direct, group, oa), and unreviewed counts
python3 "$ZALO_TOOL" chats

# 2. Inspect raw chat logs
python3 "$ZALO_TOOL" log --chat "<chat_title_or_id>" --limit 20

# 3. Search messages using full-text index
python3 "$ZALO_TOOL" search "<query>"

# 4. View pending unreviewed messages
python3 "$ZALO_TOOL" pending

# 5. Synchronize messages from active Zalo tab
python3 "$ZALO_TOOL" sync

# Target a specific chat
python3 "$ZALO_TOOL" sync --chat "<chat_title>"

# 6. Mark messages as reviewed after updating the summary
python3 "$ZALO_TOOL" ack --all

# 7. Generate or refresh master digest
python3 "$ZALO_TOOL" digest
```

---

## Ingestion Architecture

1. **In-Memory React Runtime Harvester**:
   - `zalo_tool.py` connects via `browserctl` to the active `chat.zalo.me` tab.
   - Extracts decrypted state from the React Fiber runtime without scraping complex obfuscated DOM.
2. **FTS5 Full-Text Search**:
   - Stores conversations and messages in local SQLite with an FTS5 virtual table for instant full-text searching.
3. **Delta Sync & Deduplication**:
   - Uses `msgId` and server timestamps to avoid re-ingesting existing messages.

---

## Workflow: Scheduled Digest Update

When invoked on a schedule or asked to check Zalo updates:

1. **Fetch & Check Pending**:
   - Run `python3 "$ZALO_TOOL" pending` (optionally preceded by `sync`).
   - If there are zero pending messages, report: "No new Zalo messages since last check."

2. **Analyze Discussions**:
   - Group pending messages by chat.
   - Identify:
     - Topics discussed.
     - Urgent requests, client inquiries, or blockers.
     - Action items and assigned owners.

3. **Update Master Digest In-Place**:
   - Run `python3 "$ZALO_TOOL" digest` or update `SUMMARY.md`.

4. **Acknowledge Processed Messages**:
   - Run `python3 "$ZALO_TOOL" ack --all`.

5. **Surface Delta to Chat**:
   - Output a concise summary of active discussions and pending actions in chat.
