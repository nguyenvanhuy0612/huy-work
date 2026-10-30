# Microsoft Teams Aggregator & Digest Architecture

## 1. Overview

This document outlines the architecture and implementation for an automated Microsoft Teams message collector, SQLite store, master activity digest, and periodic Antigravity scheduler workflow.

The system replaces the legacy monolithic JSON store (`msteam-database.json`) with an ACID-compliant, indexed SQLite database (`msteam.db`) using Write-Ahead Logging (WAL) and FTS5 full-text search. It aggregates all chats across the workspace into a single, continuously updated document (`msteam/SUMMARY.md`), tracks discussions, consensus, and action items, and surfaces delta summaries in chat sessions.

---

## 2. System Architecture

```
┌─────────────────────────────────┐
│   Microsoft Teams (Web Client)  │
│   teams.cloud.microsoft         │
└────────────────┬────────────────┘
                 │ (Internal chat API via browserctl bridge)
                 ▼
┌─────────────────────────────────┐
│        msteam/bridge.py         │
│  - Evaluates script in Teams    │
│  - Extracts bearer token safely │
│  - Normalizes messages          │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│          msteam/db.py           │
│  - SQLite with WAL & FTS5       │
│  - Upserts chats & messages     │
│  - Tracks review/alert flags    │
└────────┬───────────────┬────────┘
         │               │
         ▼               ▼
┌─────────────────┐  ┌──────────────────────────────────┐
│ msteam_tool.py  │  │ Antigravity Periodic Scheduler   │
│ CLI Management  │  │  1. Pulls pending (reviewed = 0) │
│ - sync          │  │  2. Updates msteam/SUMMARY.md    │
│ - log / view    │  │  3. Acknowledges reviewed state  │
│ - export        │  │  4. Prints delta digest in chat  │
│ - search        │  └──────────────────────────────────┘
└─────────────────┘
```

---

## 2.1. Verified Microsoft Teams API Contract (Stage 1 Live Survey - 2026-10-25)

Empirical network and authentication mapping verified against active Teams Web client (`teams.cloud.microsoft`):

### 1. Authentication & Identity Harvesting
- **Token Storage**: `localStorage` (Azure AD / MSAL entries).
- **Target Filter**: Key containing `accesstoken` where `target` includes `https://ic3.teams.office.com/Teams.AccessAsUser.All`.
- **Liveness Guard**: Validated via `Number(token.expiresOn) * 1000 > Date.now()`.
- **Bearer Token**: `Authorization: Bearer <token.secret>`.
- **Region Server**: Extracted from `localStorage` key matching `tmp.auth.v1.*.Discover.SKYPE-TOKEN` -> `item.userDetails.region` (e.g. `apac`).

### 2. Conversation & Chat Discovery
- **Sidebar Elements**: DOM selector `[id^="title-chat-list-item_"]`.
- **Chat ID Format**:
  - Personal / Notes: `48:notes`
  - Channels / Group Chats: `19:{uuid}@thread.v2` (e.g. `19:9ec5a0d15a7e4ee7a2c849a8acdc996b@thread.v2`)

### 3. Messaging REST Endpoint
- **URL**: `GET https://teams.cloud.microsoft/api/chatsvc/{region}/v1/users/ME/conversations/{chatId}/messages?pageSize=50`
- **Headers**:
  ```http
  Authorization: Bearer <token.secret>
  Accept: application/json
  ```
- **Cursor Pagination**:
  - Response metadata provides `_metadata.backwardLink` containing `syncState=<cursor>`.
  - Replaying `backwardLink` fetches historical messages backwards in time with zero UI manipulation.

### 4. Message Data Schema Mapping
- `id` (string): Internal timestamp-based message sequence ID.
- `clientmessageid` (string): Stable unique client identifier (primary key for deduplication).
- `type` (string): `"Message"` (used to filter out system presence events).
- `messagetype` (string): `"RichText/Html"` or `"Text"`.
- `composetime` (string): ISO 8601 creation timestamp.
- `originalarrivaltime` (string): Ingestion time at server.
- `imdisplayname` / `from` (string): Author display name.
- `content` (string): Message body (requires HTML tag stripping and entity unescaping).

---

## 2.2. Chat Classification & Conversation Identity

Microsoft Teams ChatSvc distinguishes conversation types through deterministic prefix patterns in `chat_id`:

| Type | Conversation ID Format | Structure & Semantics |
| :--- | :--- | :--- |
| **Personal Notes** | `48:notes` | Single-member personal notepad. Used for drafts, personal reminders. |
| **Direct Chat (1:1)** | `19:{oid_user1}_{oid_user2}@unq.gbl.spaces` | 2 members. No server-side title; display title resolved from counterpart. Flat message stream. |
| **Group Chat** | `19:{guid}@thread.v2` | >= 3 members. Optional custom topic title or comma-separated member list. Flat stream. |
| **Team Channel** | `19:{guid}@thread.tacv2` | Channel scoped to a `teamId`. Hierarchical message model: Root messages and Reply threads via `rootMessageId`. |

---

## 2.3. Token Harvester Pattern (Empirically Verified 2026-10-25)

Empirical testing confirmed that Microsoft Teams ChatSvc endpoints do not enforce browser-bound cookies or strict TLS fingerprinting:

```
┌───────────────────────────┐
│ Browser (Teams Web Tab)   │
└─────────────┬─────────────┘
              │ (One-time extraction ~80ms via browserctl evaluate)
              ▼
┌───────────────────────────┐
│ Token Harvester (Python)  │ ──► Caches Bearer Token + Region (TTL ~50m)
└─────────────┬─────────────┘
              │ (Browser tab completely released)
              ▼
┌───────────────────────────┐
│ Standalone Python / curl  │ ──► GET /api/chatsvc/{region}/v1/users/ME/...
└─────────────┬─────────────┘     Header: Authorization: Bearer <token>
              │                   HTTP 200 OK (Verified independently)
              ▼
┌───────────────────────────┐
│ SQLite Store (msteam.db)  │
└───────────────────────────┘
```

**Benefits**:
- Zero browser locking or UI freezing during synchronization.
- High concurrency and connection pooling via Python HTTP libraries.
- Browserctl is only invoked during initial cold start or upon receiving HTTP 401 (token refresh).

---

## 2.4. Multi-Tier Delta & Incremental Sync Strategy

To minimize redundant network calls when comparing local database state with the server:

1. **Tier 1: Conversation-Level Check (0 requests to message API)**
   - Query local SQLite: `SELECT MAX(time) FROM messages WHERE chat_id = ?;` ($T_A$).
   - Inspect conversation metadata `lastMessage.composetime`.
   - If `lastMessage.composetime <= T_A`: Chat has no new messages; skip immediately.

2. **Tier 2: Early-Break Pagination (1 single request for <= 50 new messages)**
   - The Teams ChatSvc returns messages in **descending chronological order** (`messages[0]` is newest).
   - Fetch page 1: `GET /messages?pageSize=50`.
   - Iterate from newest to oldest:
     - If `composetime > T_A`: Ingest new message into database.
     - Upon encountering the first message with `composetime <= T_A` or existing `id`:
       - **Break loop immediately**.
       - **Do not follow `_metadata.backwardLink`**.
   - Result: Synchronizing incremental traffic almost always completes in exactly 1 request.

3. **Tier 3: Server-Side Delta Cursor (`syncState`)**
   - Save `_metadata.syncState` into `chats.sync_cursor`.
   - Subsequent delta queries append the cursor; Teams server returns only messages appended after that state.

---

## 3. Database Schema (`msteam/msteam.db`)

### 3.1. Pragmas
- `PRAGMA journal_mode = WAL;` (Concurrent readers without blocking writers)
- `PRAGMA synchronous = NORMAL;` (High durability with minimal I/O overhead)
- `PRAGMA foreign_keys = ON;`
- `PRAGMA busy_timeout = 5000;`

### 3.2. Tables

#### `chats`
Stores metadata for all direct conversations, groups, tickets, and bot channels:
- `chat_id` (TEXT PRIMARY KEY): Stable Teams conversation ID.
- `title` (TEXT NOT NULL): Display title.
- `type` (TEXT NOT NULL): `direct`, `group`, `ticket`, `bot`.
- `last_activity` (TEXT): ISO 8601 or formatted timestamp of the most recent message.
- `last_scanned_at` (TEXT): Timestamp when this chat was last polled.
- `members` (TEXT): JSON array of known member display names.

#### `messages`
Stores individual normalized messages:
- `id` (TEXT PRIMARY KEY): Compound key `<chat_id>_<mid>` (or stable mid) to prevent collisions.
- `mid` (TEXT NOT NULL): Teams message ID.
- `chat_id` (TEXT NOT NULL, FOREIGN KEY): Reference to `chats(chat_id)`.
- `author` (TEXT NOT NULL): Sender display name or identifier.
- `is_mine` (INTEGER DEFAULT 0): 1 if sent by user, 0 otherwise.
- `time` (TEXT NOT NULL): Message arrival timestamp (normalized).
- `text` (TEXT): Decoded plain text content.
- `content_html` (TEXT): Original HTML or card snippet.
- `message_type` (TEXT): Message type (`Text`, `RichText/Html`, etc.).
- `observed_at` (TEXT NOT NULL): Local ingestion timestamp.
- `reviewed` (INTEGER DEFAULT 0): 0 = pending analysis, 1 = analyzed/summarized.
- `alerted` (INTEGER DEFAULT 0): 0 = pending alert, 1 = notified.
- `raw_json` (TEXT): Serialized attachments, reactions, and link metadata.

#### `messages_fts` (Virtual Table)
Full-Text Search index using SQLite FTS5:
- `mid` UNINDEXED
- `chat_id` UNINDEXED
- `author`
- `text`

---

## 4. Master Digest Hub (`msteam/SUMMARY.md`)

All chats and discussions across the workspace are synthesized into a single file `msteam/SUMMARY.md`:

1. **Executive Dashboard**: A master table displaying all conversations, types, latest hot topics, key decisions, and operational status.
2. **Channel Digests**: Per-conversation deep dives:
   - Purpose and active members.
   - Ongoing topics and perspectives from different participants.
   - Agreements, consensus, and final decisions (`Resolved`, `Pending`).
   - Action items and assigned owners.
3. **Master Action Items & Decision Log**: Consolidated backlog of all decisions and pending tasks across all chats.

---

## 5. Inspection and Raw Data Viewing

Users can view raw data using three methods:
1. **CLI Commands**:
   - `python3 msteam/msteam_tool.py log --chat "<name>" --limit 20`
   - `python3 msteam/msteam_tool.py export --chat "<name>" --format md --output chat.md`
   - `python3 msteam/msteam_tool.py export --format json --output db.json`
2. **Editor Extension**: VS Code / Cursor "SQLite Viewer" for interactive table browsing.
3. **Desktop GUI**: DB Browser for SQLite on macOS and Windows.

---

## 6. Antigravity Skill & Scheduler Workflow

- The skill `msteam` is defined at `claude-setup/skills/msteam/SKILL.md`.
- When triggered periodically by `/schedule`:
  1. Executes `msteam_tool.py sync` or queries `pending` messages (`reviewed = 0`).
  2. If new messages exist, generates contextual topic summaries and in-place updates `msteam/SUMMARY.md`.
  3. Acknowledges reviewed messages (`reviewed = 1`).
  4. Formats a brief, actionable delta report directly into the chat session for immediate follow-up.
