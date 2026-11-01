---
name: chat
description: >-
  Inspects, searches, synchronizes, summarizes, and dispatches messages across Microsoft Teams
  and Zalo Web. Uses local SQLite database with FTS5 full-text search. Trigger when the user asks
  about Teams or Zalo messages, unread chats, decisions, or asks to send/reply to chat messages.
---

# Chat Skill (Microsoft Teams & Zalo Web)

Unified tool for Microsoft Teams and Zalo Web message ingestion, querying, activity digest maintenance, and controlled message dispatch.

## Core Responsibilities

1. **Discussions & History**: Query historical messages and discussions across Teams and Zalo using full-text search (FTS5) or per-chat log inspection.
2. **Synchronization**: Pull new messages from active browser tabs via the local browser bridge (`browserctl`) into `skills/chat/chat.db`.
3. **Outbound Messaging (Write)**: Draft and send messages to Teams channels/direct chats (via ChatSvc REST API) or Zalo conversations.
4. **Safety & Approval**: All outbound send commands require explicit user confirmation before executing. Never send without showing the exact message preview first.

---

## Tool Reference

The CLI utility lives at `skills/chat/chat_tool.py`:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
CHAT_TOOL="$REPO_ROOT/skills/chat/chat_tool.py"

# 1. View all conversations, pending counts, and types (Teams & Zalo)
python3 "$CHAT_TOOL" list
# Filter by app:
python3 "$CHAT_TOOL" --app teams list
python3 "$CHAT_TOOL" --app zalo list

# 2. Inspect chat logs
python3 "$CHAT_TOOL" --app teams log --chat "<chat_title_or_id>" --limit 20
python3 "$CHAT_TOOL" --app zalo log --chat "<chat_title_or_id>" --limit 20

# 3. Full-text search across all platforms (or filtered by --app)
python3 "$CHAT_TOOL" search "<query>"
python3 "$CHAT_TOOL" --app teams search "<query>"

# 4. View pending unreviewed messages
python3 "$CHAT_TOOL" pending
python3 "$CHAT_TOOL" --app teams pending

# 5. Synchronize messages from browser tabs
python3 "$CHAT_TOOL" --app teams sync
python3 "$CHAT_TOOL" --app zalo sync

# 6. Acknowledge messages after review
python3 "$CHAT_TOOL" ack --all
python3 "$CHAT_TOOL" --app teams ack --all

# 7. Send outbound message (Dry run preview by default; requires --confirm)
# Preview first:
python3 "$CHAT_TOOL" --app teams send --chat "<chat_title_or_id>" --message "<content>"
# Dispatch upon explicit approval:
python3 "$CHAT_TOOL" --app teams send --chat "<chat_title_or_id>" --message "<content>" --confirm

# 8. Export chat history to markdown
python3 "$CHAT_TOOL" --app teams export --chat "<chat_id>" --output "export.md"
```

---

## Safety Guardrail

Before running `send --confirm`:
1. Execute the command without `--confirm` to generate the `[OUTBOUND ACTION PREVIEW]`.
2. Present the exact recipient, target chat, and message content to the user in chat.
3. Wait for explicit go-ahead from the user before re-running with `--confirm`.

