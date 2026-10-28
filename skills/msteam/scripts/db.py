"""SQLite storage layer for Microsoft Teams messages and conversation metadata."""

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_default_db_path() -> Path:
    return Path(__file__).resolve().parent / "msteam.db"


def classify_chat_type(chat_id: str) -> str:
    """Classifies Microsoft Teams chat type based on chat_id prefix/suffix conventions."""
    cid = (chat_id or "").strip().lower()
    if cid == "48:notes" or cid.startswith("48:"):
        return "personal"
    if "@unq.gbl.spaces" in cid:
        return "direct"
    if "@thread.tacv2" in cid:
        return "channel"
    if "@thread.v2" in cid:
        return "group"
    return "group"


def get_db_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    target = db_path or get_default_db_path()
    conn = sqlite3.connect(str(target), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                type TEXT NOT NULL,
                last_activity TEXT,
                last_scanned_at TEXT,
                sync_cursor TEXT,
                members TEXT
            );
        """)

        # Seamless schema migration for existing databases without sync_cursor
        cursor = conn.execute("PRAGMA table_info(chats);")
        columns = {row["name"] for row in cursor.fetchall()}
        if "sync_cursor" not in columns:
            conn.execute("ALTER TABLE chats ADD COLUMN sync_cursor TEXT;")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                mid TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                author TEXT NOT NULL,
                is_mine INTEGER DEFAULT 0,
                time TEXT NOT NULL,
                text TEXT,
                content_html TEXT,
                message_type TEXT,
                observed_at TEXT NOT NULL,
                reviewed INTEGER DEFAULT 0,
                alerted INTEGER DEFAULT 0,
                raw_json TEXT,
                FOREIGN KEY(chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
            );
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_time ON messages(chat_id, time DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_pending ON messages(reviewed, alerted, time DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_mid ON messages(mid);")

        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                mid UNINDEXED,
                chat_id UNINDEXED,
                author,
                text,
                tokenize = 'unicode61'
            );
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(mid, chat_id, author, text)
                VALUES (new.mid, new.chat_id, new.author, IFNULL(new.text, ''));
            END;
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_messages_ad AFTER DELETE ON messages BEGIN
                DELETE FROM messages_fts WHERE mid = old.mid AND chat_id = old.chat_id;
            END;
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_messages_au AFTER UPDATE ON messages BEGIN
                DELETE FROM messages_fts WHERE mid = old.mid AND chat_id = old.chat_id;
                INSERT INTO messages_fts(mid, chat_id, author, text)
                VALUES (new.mid, new.chat_id, new.author, IFNULL(new.text, ''));
            END;
        """)


def upsert_chat(
    conn: sqlite3.Connection,
    chat_id: str,
    title: str,
    chat_type: Optional[str] = None,
    last_activity: Optional[str] = None,
    last_scanned_at: Optional[str] = None,
    sync_cursor: Optional[str] = None,
    members: Optional[List[str]] = None,
) -> None:
    resolved_type = chat_type or classify_chat_type(chat_id)
    members_json = json.dumps(sorted(list(set(members or []))), ensure_ascii=False)
    with conn:
        conn.execute("""
            INSERT INTO chats (chat_id, title, type, last_activity, last_scanned_at, sync_cursor, members)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                title = excluded.title,
                type = CASE WHEN excluded.type != '' THEN excluded.type ELSE chats.type END,
                last_activity = CASE WHEN excluded.last_activity IS NOT NULL AND excluded.last_activity > IFNULL(chats.last_activity, '')
                                     THEN excluded.last_activity ELSE chats.last_activity END,
                last_scanned_at = COALESCE(excluded.last_scanned_at, chats.last_scanned_at),
                sync_cursor = COALESCE(excluded.sync_cursor, chats.sync_cursor),
                members = CASE WHEN excluded.members != '[]' THEN excluded.members ELSE chats.members END;
        """, (chat_id, title, resolved_type, last_activity, last_scanned_at, sync_cursor, members_json))


def get_chat_latest_message_info(conn: sqlite3.Connection, chat_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Returns (latest_time, latest_mid) for the given chat_id to support early-break delta sync."""
    cursor = conn.execute(
        "SELECT time, mid FROM messages WHERE chat_id = ? ORDER BY time DESC LIMIT 1;",
        (chat_id,)
    )
    row = cursor.fetchone()
    if row:
        return row["time"], row["mid"]
    return None, None


def get_chat_sync_cursor(conn: sqlite3.Connection, chat_id: str) -> Optional[str]:
    """Returns stored server syncState cursor for delta pagination."""
    cursor = conn.execute("SELECT sync_cursor FROM chats WHERE chat_id = ?;", (chat_id,))
    row = cursor.fetchone()
    return row["sync_cursor"] if row else None


def insert_message(conn: sqlite3.Connection, msg: Dict[str, Any]) -> bool:
    mid = str(msg.get("mid") or msg.get("id") or "").strip()
    chat_id = str(msg.get("chat_id") or msg.get("chatId") or "").strip()
    if not chat_id:
        raise ValueError("Message must have a valid chat_id.")

    # Generate composite ID if mid is empty or shared across threads
    msg_id = f"{chat_id}_{mid}" if mid else f"{chat_id}_{msg.get('time', '')}_{msg.get('author', '')}"
    
    time_val = msg.get("time") or msg.get("timeIso") or ""
    author = msg.get("author") or "Unknown"
    text = msg.get("text") or ""
    content_html = msg.get("contentHtml") or msg.get("content_html") or ""
    message_type = msg.get("messageType") or msg.get("message_type") or "Text"
    observed_at = msg.get("observedAt") or msg.get("observed_at") or time_val
    is_mine = 1 if msg.get("isMine") or msg.get("is_mine") else 0
    reviewed = 1 if msg.get("reviewed") else 0
    alerted = 1 if msg.get("alerted") else 0

    raw_data = {
        "attachments": msg.get("attachments") or [],
        "reactions": msg.get("reactions") or [],
        "links": msg.get("links") or [],
    }
    raw_json = json.dumps(raw_data, ensure_ascii=False)

    with conn:
        existing = conn.execute("SELECT 1 FROM messages WHERE id = ?", (msg_id,)).fetchone()
        conn.execute("""
            INSERT INTO messages (
                id, mid, chat_id, author, is_mine, time, text,
                content_html, message_type, observed_at, reviewed, alerted, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                text = CASE WHEN excluded.text != '' THEN excluded.text ELSE messages.text END,
                content_html = CASE WHEN excluded.content_html != '' THEN excluded.content_html ELSE messages.content_html END,
                raw_json = excluded.raw_json;
        """, (
            msg_id, mid, chat_id, author, is_mine, time_val, text,
            content_html, message_type, observed_at, reviewed, alerted, raw_json
        ))
        inserted = existing is None

    return inserted


def insert_messages_batch(conn: sqlite3.Connection, messages: List[Dict[str, Any]]) -> int:
    inserted_count = 0
    with conn:
        for msg in messages:
            if insert_message(conn, msg):
                inserted_count += 1
    return inserted_count


def get_pending_messages(conn: sqlite3.Connection, chat_id: Optional[str] = None) -> List[sqlite3.Row]:
    if chat_id:
        cursor = conn.execute("""
            SELECT m.*, c.title as chat_title, c.type as chat_type
            FROM messages m
            JOIN chats c ON m.chat_id = c.chat_id
            WHERE m.reviewed = 0 AND m.chat_id = ?
            ORDER BY m.time ASC;
        """, (chat_id,))
    else:
        cursor = conn.execute("""
            SELECT m.*, c.title as chat_title, c.type as chat_type
            FROM messages m
            JOIN chats c ON m.chat_id = c.chat_id
            WHERE m.reviewed = 0
            ORDER BY m.chat_id, m.time ASC;
        """)
    return cursor.fetchall()


def acknowledge_messages(conn: sqlite3.Connection, message_ids: List[str]) -> int:
    if not message_ids:
        return 0
    placeholders = ",".join("?" for _ in message_ids)
    with conn:
        cursor = conn.execute(f"""
            UPDATE messages
            SET reviewed = 1, alerted = 1
            WHERE id IN ({placeholders});
        """, message_ids)
        return cursor.rowcount


def get_chats(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    cursor = conn.execute("""
        SELECT c.*,
               COUNT(m.id) as total_messages,
               SUM(CASE WHEN m.reviewed = 0 THEN 1 ELSE 0 END) as unreviewed_messages
        FROM chats c
        LEFT JOIN messages m ON c.chat_id = m.chat_id
        GROUP BY c.chat_id
        ORDER BY c.last_activity DESC, c.title ASC;
    """)
    return cursor.fetchall()


def get_messages(
    conn: sqlite3.Connection,
    chat_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    author: Optional[str] = None,
    search: Optional[str] = None,
) -> List[sqlite3.Row]:
    query = """
        SELECT m.*, c.title as chat_title, c.type as chat_type
        FROM messages m
        JOIN chats c ON m.chat_id = c.chat_id
        WHERE 1=1
    """
    params: List[Any] = []

    if chat_id:
        query += " AND (m.chat_id = ? OR c.title LIKE ?)"
        params.extend([chat_id, f"%{chat_id}%"])
    if author:
        query += " AND m.author LIKE ?"
        params.append(f"%{author}%")
    if search:
        query += " AND m.text LIKE ?"
        params.append(f"%{search}%")

    query += " ORDER BY m.time DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = conn.execute(query, params)
    return cursor.fetchall()


def search_fts(conn: sqlite3.Connection, query: str, limit: int = 50) -> List[sqlite3.Row]:
    cursor = conn.execute("""
        SELECT m.*, c.title as chat_title, c.type as chat_type,
               snippet(messages_fts, 3, '<b>', '</b>', '...', 15) as highlighted_snippet
        FROM messages_fts f
        JOIN messages m ON f.mid = m.mid AND f.chat_id = m.chat_id
        JOIN chats c ON m.chat_id = c.chat_id
        WHERE messages_fts MATCH ?
        ORDER BY rank
        LIMIT ?;
    """, (query, limit))
    return cursor.fetchall()


def migrate_from_json(json_file_path: Path, db_path: Optional[Path] = None) -> Tuple[int, int]:
    """Migrates historical data from msteam-database.json into SQLite."""
    if not json_file_path.exists():
        raise FileNotFoundError(f"JSON source not found: {json_file_path}")

    with open(json_file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    conn = get_db_connection(db_path)
    try:
        init_db(conn)

        groups = data.get("groups", {})
        total_chats = 0
        total_messages = 0

        with conn:
            for group_name, gdata in groups.items():
                chat_id = gdata.get("chatId") or group_name
                chat_type = gdata.get("type") or "group"
                last_activity = gdata.get("lastActivity") or ""
                members = gdata.get("members") or []

                upsert_chat(
                    conn,
                    chat_id=chat_id,
                    title=group_name,
                    chat_type=chat_type,
                    last_activity=last_activity,
                    members=members,
                )
                total_chats += 1

                msgs = gdata.get("messages", [])
                for m in msgs:
                    insert_message(conn, {
                        "mid": m.get("id") or m.get("mid") or "",
                        "chat_id": chat_id,
                        "author": m.get("author") or "Unknown",
                        "time": m.get("time") or m.get("timeIso") or "",
                        "text": m.get("text") or "",
                        "isMine": m.get("isMine", False),
                        "attachments": m.get("attachments", []),
                        "reactions": m.get("reactions", []),
                        "links": m.get("links", []),
                        "reviewed": 1,  # Historical messages already imported are marked reviewed
                        "alerted": 1,
                    })
                    total_messages += 1

        return total_chats, total_messages
    finally:
        conn.close()
