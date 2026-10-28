"""SQLite storage layer for Zalo messages and conversation metadata."""

import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_default_db_path() -> Path:
    return Path(__file__).resolve().parent / "zalo.db"


def classify_chat_type(chat_id: str, is_group: bool = False, is_oa: bool = False) -> str:
    """Classifies Zalo conversation into: 'group', 'oa', 'cloud', or 'direct'."""
    cid = (chat_id or "").strip()
    if cid in ("0", "cloud", "div_TabMsg_ThrdChFileXFER") or cid.lower().startswith("cloud_"):
        return "cloud"
    if is_oa or cid.startswith("oa_"):
        return "oa"
    if is_group or cid.startswith("g"):
        return "group"
    return "direct"


def format_zalo_timestamp(ts: Any) -> str:
    """Formats numeric epoch timestamp (ms or s) into standard ISO 8601 string."""
    if not ts:
        return ""
    if isinstance(ts, str):
        cleaned = ts.strip()
        if "T" in cleaned or "-" in cleaned:
            return cleaned
        try:
            val = float(cleaned)
        except ValueError:
            return cleaned
    elif isinstance(ts, (int, float)):
        val = float(ts)
    else:
        return str(ts)

    try:
        # If timestamp is in milliseconds (greater than ~3 years in seconds: 1e11)
        if val > 100_000_000_000:
            sec = val / 1000.0
        else:
            sec = val
        dt = datetime.datetime.fromtimestamp(sec, tz=datetime.timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except Exception:
        return str(ts)


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
                unread_count INTEGER DEFAULT 0,
                members TEXT,
                avatar TEXT,
                raw_json TEXT
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                msg_id TEXT NOT NULL,
                cli_msg_id TEXT,
                chat_id TEXT NOT NULL,
                author TEXT NOT NULL,
                from_uid TEXT NOT NULL,
                to_uid TEXT NOT NULL,
                is_mine INTEGER DEFAULT 0,
                time TEXT NOT NULL,
                text TEXT,
                message_type TEXT,
                observed_at TEXT NOT NULL,
                reviewed INTEGER DEFAULT 0,
                alerted INTEGER DEFAULT 0,
                raw_json TEXT,
                FOREIGN KEY(chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
            );
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_zalo_messages_chat_time ON messages(chat_id, time DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_zalo_messages_pending ON messages(reviewed, alerted, time DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_zalo_messages_msg_id ON messages(msg_id);")

        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                msg_id UNINDEXED,
                chat_id UNINDEXED,
                author,
                text,
                tokenize = 'unicode61'
            );
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_zalo_messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(msg_id, chat_id, author, text)
                VALUES (new.msg_id, new.chat_id, new.author, IFNULL(new.text, ''));
            END;
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_zalo_messages_ad AFTER DELETE ON messages BEGIN
                DELETE FROM messages_fts WHERE msg_id = old.msg_id AND chat_id = old.chat_id;
            END;
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_zalo_messages_au AFTER UPDATE ON messages BEGIN
                DELETE FROM messages_fts WHERE msg_id = old.msg_id AND chat_id = old.chat_id;
                INSERT INTO messages_fts(msg_id, chat_id, author, text)
                VALUES (new.msg_id, new.chat_id, new.author, IFNULL(new.text, ''));
            END;
        """)


def upsert_chat(
    conn: sqlite3.Connection,
    chat_id: str,
    title: str,
    chat_type: Optional[str] = None,
    last_activity: Optional[str] = None,
    last_scanned_at: Optional[str] = None,
    unread_count: int = 0,
    members: Optional[List[str]] = None,
    avatar: Optional[str] = None,
    raw_data: Optional[Dict[str, Any]] = None,
) -> None:
    resolved_type = chat_type or classify_chat_type(chat_id)
    members_json = json.dumps(sorted(list(set(members or []))), ensure_ascii=False)
    raw_json = json.dumps(raw_data or {}, ensure_ascii=False)
    activity_iso = format_zalo_timestamp(last_activity)

    with conn:
        conn.execute("""
            INSERT INTO chats (chat_id, title, type, last_activity, last_scanned_at, unread_count, members, avatar, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                title = excluded.title,
                type = CASE WHEN excluded.type != '' THEN excluded.type ELSE chats.type END,
                last_activity = CASE WHEN excluded.last_activity IS NOT NULL AND excluded.last_activity > IFNULL(chats.last_activity, '')
                                     THEN excluded.last_activity ELSE chats.last_activity END,
                last_scanned_at = COALESCE(excluded.last_scanned_at, chats.last_scanned_at),
                unread_count = excluded.unread_count,
                members = CASE WHEN excluded.members != '[]' THEN excluded.members ELSE chats.members END,
                avatar = COALESCE(excluded.avatar, chats.avatar),
                raw_json = excluded.raw_json;
        """, (chat_id, title, resolved_type, activity_iso, last_scanned_at, unread_count, members_json, avatar, raw_json))


def get_chat_latest_message_info(conn: sqlite3.Connection, chat_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Returns (latest_time, latest_msg_id) for the given chat_id to support delta sync."""
    cursor = conn.execute(
        "SELECT time, msg_id FROM messages WHERE chat_id = ? ORDER BY time DESC LIMIT 1;",
        (chat_id,)
    )
    row = cursor.fetchone()
    if row:
        return row["time"], row["msg_id"]
    return None, None


def insert_message(conn: sqlite3.Connection, msg: Dict[str, Any]) -> bool:
    msg_id_val = str(msg.get("msg_id") or msg.get("msgId") or "").strip()
    cli_msg_id = str(msg.get("cli_msg_id") or msg.get("cliMsgId") or "").strip()
    chat_id = str(msg.get("chat_id") or msg.get("convId") or msg.get("toUid") or "").strip()
    if not chat_id:
        raise ValueError("Message must have a valid chat_id.")

    # Unique identifier
    if msg_id_val and msg_id_val != "0":
        id_key = f"{chat_id}_{msg_id_val}"
    elif cli_msg_id:
        id_key = f"{chat_id}_{cli_msg_id}"
    else:
        id_key = f"{chat_id}_{msg.get('time', '')}_{msg.get('from_uid', '')}"

    time_val = format_zalo_timestamp(msg.get("time") or msg.get("messageTime") or msg.get("sendDttm") or "")
    author = msg.get("author") or msg.get("senderName") or msg.get("dName") or "Unknown"
    from_uid = str(msg.get("from_uid") or msg.get("fromUid") or "").strip()
    to_uid = str(msg.get("to_uid") or msg.get("toUid") or chat_id).strip()
    text = msg.get("text") or msg.get("message") or ""
    if isinstance(text, dict):
        text = text.get("title") or text.get("description") or json.dumps(text, ensure_ascii=False)
    message_type = str(msg.get("message_type") or msg.get("msgType") or "Text")
    observed_at = msg.get("observed_at") or time_val
    is_mine = 1 if (msg.get("is_mine") or msg.get("isMine") or from_uid == "0") else 0
    reviewed = 1 if msg.get("reviewed") else 0
    alerted = 1 if msg.get("alerted") else 0

    raw_data = {
        "properties": msg.get("properties") or {},
        "quote": msg.get("quote") or {},
        "mentions": msg.get("mentions") or [],
        "cliMsgId": cli_msg_id,
    }
    raw_json = json.dumps(raw_data, ensure_ascii=False)

    with conn:
        existing = conn.execute("SELECT 1 FROM messages WHERE id = ?", (id_key,)).fetchone()
        conn.execute("""
            INSERT INTO messages (
                id, msg_id, cli_msg_id, chat_id, author, from_uid, to_uid,
                is_mine, time, text, message_type, observed_at, reviewed, alerted, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                text = CASE WHEN excluded.text != '' THEN excluded.text ELSE messages.text END,
                author = CASE WHEN excluded.author != 'Unknown' THEN excluded.author ELSE messages.author END,
                raw_json = excluded.raw_json;
        """, (
            id_key, msg_id_val, cli_msg_id, chat_id, author, from_uid, to_uid,
            is_mine, time_val, text, message_type, observed_at, reviewed, alerted, raw_json
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


def get_chats(conn: sqlite3.Connection, category: Optional[str] = None) -> List[sqlite3.Row]:
    if category:
        cursor = conn.execute("""
            SELECT * FROM chats
            WHERE type = ?
            ORDER BY IFNULL(last_activity, '') DESC, title ASC;
        """, (category,))
    else:
        cursor = conn.execute("""
            SELECT * FROM chats
            ORDER BY IFNULL(last_activity, '') DESC, title ASC;
        """)
    return cursor.fetchall()


def get_messages(conn: sqlite3.Connection, chat_id: str, limit: int = 50) -> List[sqlite3.Row]:
    cursor = conn.execute("""
        SELECT * FROM messages
        WHERE chat_id = ?
        ORDER BY time DESC
        LIMIT ?;
    """, (chat_id, limit))
    rows = cursor.fetchall()
    return list(reversed(rows))


def search_fts(conn: sqlite3.Connection, query_term: str, limit: int = 50) -> List[sqlite3.Row]:
    clean_query = query_term.replace('"', '""').strip()
    if not clean_query:
        return []
    cursor = conn.execute("""
        SELECT m.*, c.title as chat_title, c.type as chat_type,
               snippet(messages_fts, 3, '<b>', '</b>', '...', 12) as match_snippet
        FROM messages_fts f
        JOIN messages m ON f.msg_id = m.msg_id AND f.chat_id = m.chat_id
        JOIN chats c ON m.chat_id = c.chat_id
        WHERE messages_fts MATCH ?
        ORDER BY m.time DESC
        LIMIT ?;
    """, (f'"{clean_query}"', limit))
    return cursor.fetchall()
