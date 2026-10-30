# Zalo Web Message Aggregator & Ingestion Architecture

## 1. Overview

This document describes the architecture, empirical findings, and implementation of the Zalo Web automated message collector, local SQLite store, FTS5 full-text search engine, and activity digest generator.

Zalo Web (`chat.zalo.me`) uses a local-first, Progressive Web App (PWA) architecture:
- Messages and threads are delivered via binary/JSON WebSocket streams.
- Persistent storage on disk (`IndexedDB/zdb_<userId>`) is locally encrypted using symmetric keys.
- Directly simulating external REST API requests via `curl` or Python is fragile due to complex session cookies (`__zi`, `zpw_sek`, `_zlang`) and proprietary request checksums.
- However, the running React application inside the active Chrome tab maintains a **fully decrypted, normalized in-memory state tree** and controllers (`convlistController`, `state.contacts`, `state.groups`, `previewManager`).

To achieve reliability, speed, and zero DOM fragility, this system implements an **In-Memory React Runtime Harvester**: evaluating lightweight JavaScript routines directly inside the active Zalo Web tab via the local browser bridge (`browserctl`) to extract decrypted models directly from React memory into an indexed SQLite database (`zalo.db`).

---

## 2. System Architecture

```
┌─────────────────────────────────┐
│       Zalo Web Application      │
│       https://chat.zalo.me      │
│  - React 16/17 Fiber Tree       │
│  - In-Memory Decrypted State    │
│  - convlistController & _pm     │
└────────────────┬────────────────┘
                 │ (eval_js via browserctl bridge: 127.0.0.1:8765)
                 ▼
┌─────────────────────────────────┐
│        zalo/bridge.py           │
│  - Finds active Zalo tab        │
│  - In-page controller traversal │
│  - Harvests contacts & groups   │
│  - Extracts decrypted previews  │
│  - Selects thread for deep sync │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│          zalo/db.py             │
│  - SQLite with WAL & FTS5       │
│  - Chats & Messages tables      │
│  - Triggers for FTS sync        │
│  - Reviews & alerts tracking    │
└────────┬───────────────┬────────┘
         │               │
         ▼               ▼
┌─────────────────┐  ┌──────────────────────────────────┐
│  zalo_tool.py   │  │ personal/zalo/SUMMARY.md         │
│  CLI Management │  │  - Executive Dashboard           │
│  - sync         │  │  - Channel & Contact Digests     │
│  - chats / log  │  │  - Active/Unread status tracking │
│  - search (FTS) │  └──────────────────────────────────┘
│  - digest       │
└─────────────────┘
```

---

## 3. Database Schema (`zalo/db.py`)

### 3.1. `chats` Table
Stores conversation thread metadata, categorization, member lists, and last activity timestamps:

| Column | Type | Description |
| :--- | :--- | :--- |
| `chat_id` | `TEXT PRIMARY KEY` | Zalo conversation ID (e.g., `7792528564668089393`, `g1191331066876269725`, `0`) |
| `title` | `TEXT NOT NULL` | Resolved display name of contact or group |
| `type` | `TEXT NOT NULL` | Classification: `direct`, `group`, `oa` (Official Account), or `cloud` (File Transfer) |
| `last_activity` | `TEXT` | Standard ISO 8601 UTC timestamp of the latest activity |
| `last_scanned_at`| `TEXT` | Timestamp of the last local scan |
| `unread_count` | `INTEGER` | Unread message count |
| `members` | `TEXT` | JSON array of participant display names/IDs |
| `avatar` | `TEXT` | Avatar URL |
| `raw_json` | `TEXT` | Raw metadata JSON |

### 3.2. `messages` Table
Stores individual messages with author attribution and review status:

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `TEXT PRIMARY KEY` | Composite ID: `{chat_id}_{msg_id}` or `{chat_id}_{cli_msg_id}` |
| `msg_id` | `TEXT NOT NULL` | Server message ID |
| `cli_msg_id` | `TEXT` | Client message ID |
| `chat_id` | `TEXT NOT NULL` | Foreign key referencing `chats(chat_id)` |
| `author` | `TEXT NOT NULL` | Author display name (or current user name if `is_mine`) |
| `from_uid` | `TEXT NOT NULL` | Sender user ID (`0` indicates current user) |
| `to_uid` | `TEXT NOT NULL` | Target user ID or thread ID |
| `is_mine` | `INTEGER` | `1` if sent by the current user, `0` otherwise |
| `time` | `TEXT NOT NULL` | Standard ISO 8601 UTC timestamp |
| `text` | `TEXT` | Plain text message body |
| `message_type` | `TEXT` | Type of message (`Text`, `Photo`, `Call`, `Sticker`, `File`) |
| `observed_at` | `TEXT NOT NULL` | Ingestion timestamp |
| `reviewed` | `INTEGER` | `0` = pending review, `1` = acknowledged |
| `alerted` | `INTEGER` | `0` = unalerted, `1` = alerted |
| `raw_json` | `TEXT` | JSON containing properties, quotes, and mentions |

### 3.3. Full-Text Search Virtual Table (`messages_fts`)
An SQLite FTS5 table indexing `author` and `text` with `unicode61` tokenizer, synchronized automatically through database triggers (`AFTER INSERT`, `AFTER UPDATE`, `AFTER DELETE`).

---

## 4. In-Memory React Runtime Harvester (`zalo/bridge.py`)

### 4.1. Navigation & State Discovery
The harvester traverses the React Internal Instance tree attached to sidebar nodes (`.msg-item`):
1. **User Profile**: Discovered on React Fiber props:
   - `userId`: e.g. `1488132322898755251`
   - `displayName`, `phoneNumber`, `avatar`
2. **Contacts & Groups Store**:
   - `state.contacts`: Map of all contacts with profiles and phone numbers.
   - `state.groups`: Map of all group definitions, member IDs, and creator IDs.
3. **Conversation List & Previews**:
   - `convlistController.listVisible` / `convlistController.listRawAll`: Ordered thread IDs.
   - `convlistController._pm.getAllPreviewsSync()`: Synchronous access to in-memory decrypted message previews.
4. **Active Chat Messages**:
   - Scanned from `.chat-message` DOM elements accessing the React Fiber `props.data` object.
5. **Thread Switching**:
   - Executing `convlistController.selectConversation(id)` triggers seamless thread switching for deep message history retrieval without DOM simulation.

---

## 5. Command-Line Interface (`zalo/zalo_tool.py`)

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `sync` | `[--chat <filter>] [--deep] [--limit-chats N]` | Synchronize conversations and messages from Zalo tab into SQLite |
| `chats` | `[--category direct\|group\|oa\|cloud]` | List all chats with message counts and unread status |
| `log` | `[--chat <id/title>] [--limit N]` | Display formatted chronological message log |
| `search`| `<query> [--limit N]` | Search message history using SQLite FTS5 full-text search |
| `pending`| `[--chat <id>]` | Display incoming messages requiring review |
| `ack` | `[--ids <ids...>] [--all]` | Mark pending messages as reviewed |
| `export` | `[--chat <id>] [--format md\|json]` | Export messages to Markdown or JSON |
| `digest` | `[--output <path>]` | Generate or update `zalo/SUMMARY.md` master activity digest |

---

## 6. Verification & Quality Assurance

- **Unit Tests**: 21 colocated tests covering all components:
  - `zalo/test_db.py`: Schema creation, categorizations, timestamps, batch inserts, FTS5 search.
  - `zalo/test_bridge.py`: Normalization, cache TTL, mock tab discovery, in-page extraction.
  - `zalo/test_zalo_tool.py`: CLI commands (`chats`, `log`, `search`, `pending`, `ack`, `export`, `digest`, `sync`).
- **Live Tab Verification**: Verified against live Chrome tab `414190273` (`Zalo - Nguyễn Văn Huy`), successfully ingesting real threads and messages.
