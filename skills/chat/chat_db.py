"""SQLite storage layer for Chat domain (Teams and Zalo)."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from skills.common.storage import clean_fts_query, get_db_connection


def get_default_db_path() -> Path:
    return Path(__file__).resolve().parent / "chat.db"


def init_db(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                app TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT DEFAULT 'group',
                last_activity TEXT,
                unread_count INTEGER DEFAULT 0,
                members TEXT,
                sync_cursor TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (app, chat_id)
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chats_app ON chats(app);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chats_activity ON chats(last_activity DESC);")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                app TEXT NOT NULL,
                mid TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                author TEXT NOT NULL,
                is_mine INTEGER DEFAULT 0,
                time TEXT NOT NULL,
                text TEXT NOT NULL,
                content_html TEXT,
                message_type TEXT DEFAULT 'Text',
                reviewed INTEGER DEFAULT 0,
                observed_at TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (app, mid),
                FOREIGN KEY (app, chat_id) REFERENCES chats(app, chat_id) ON DELETE CASCADE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_app_chat ON messages(app, chat_id, time DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_app_reviewed ON messages(app, reviewed);")

        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                app UNINDEXED,
                mid UNINDEXED,
                chat_id UNINDEXED,
                author,
                text,
                tokenize = 'unicode61'
            );
        """)


def classify_chat_type(chat_id: str) -> str:
    """Infers chat type from protocol identifier."""
    if chat_id.startswith("48:"):
        return "personal"
    if "@unq.gbl.spaces" in chat_id:
        return "direct"
    if "@thread.tacv2" in chat_id:
        return "channel"
    if chat_id.startswith("g") or "@thread.v2" in chat_id:
        return "group"
    if chat_id == "0" or chat_id.startswith("cloud"):
        return "cloud"
    if chat_id.isdigit():
        return "direct"
    return "group"


def upsert_chat(
    conn: sqlite3.Connection,
    app: str,
    chat_id: str,
    title: str,
    category: str = "group",
    last_activity: Optional[str] = None,
    unread_count: int = 0,
    members: Optional[List[str]] = None,
    sync_cursor: Optional[str] = None,
) -> None:
    members_json = json.dumps(members or [], ensure_ascii=False)
    with conn:
        conn.execute(
            """
            INSERT INTO chats (app, chat_id, title, category, last_activity, unread_count, members, sync_cursor, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(app, chat_id) DO UPDATE SET
                title = excluded.title,
                category = excluded.category,
                last_activity = COALESCE(excluded.last_activity, chats.last_activity),
                unread_count = excluded.unread_count,
                members = CASE WHEN excluded.members = '[]' THEN chats.members ELSE excluded.members END,
                sync_cursor = COALESCE(excluded.sync_cursor, chats.sync_cursor),
                updated_at = CURRENT_TIMESTAMP;
            """,
            (app, chat_id, title, category, last_activity, unread_count, members_json, sync_cursor),
        )


def insert_message(conn: sqlite3.Connection, app: str, msg: Dict[str, Any]) -> bool:
    """Inserts message and syncs FTS index. Returns True if newly inserted."""
    mid = str(msg["mid"])
    chat_id = str(msg["chat_id"])
    author = str(msg.get("author") or "Unknown")
    is_mine = 1 if msg.get("is_mine") else 0
    time_val = str(msg.get("time") or "")
    text = str(msg.get("text") or "")
    content_html = msg.get("content_html")
    message_type = str(msg.get("message_type") or "Text")
    observed_at = msg.get("observed_at") or time_val

    with conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO messages (app, mid, chat_id, author, is_mine, time, text, content_html, message_type, observed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (app, mid, chat_id, author, is_mine, time_val, text, content_html, message_type, observed_at),
        )
        if cursor.rowcount > 0:
            conn.execute(
                """
                INSERT INTO messages_fts (app, mid, chat_id, author, text)
                VALUES (?, ?, ?, ?, ?);
                """,
                (app, mid, chat_id, author, text),
            )
            return True
        return False


def insert_messages_batch(conn: sqlite3.Connection, app: str, messages: List[Dict[str, Any]]) -> int:
    inserted = 0
    with conn:
        for m in messages:
            if insert_message(conn, app, m):
                inserted += 1
    return inserted


def get_chats(conn: sqlite3.Connection, app: Optional[str] = None) -> List[sqlite3.Row]:
    query = """
        SELECT c.*,
               COUNT(m.mid) as total_messages,
               SUM(CASE WHEN m.reviewed = 0 THEN 1 ELSE 0 END) as pending_count
        FROM chats c
        LEFT JOIN messages m ON c.app = m.app AND c.chat_id = m.chat_id
    """
    params = []
    if app:
        query += " WHERE c.app = ?"
        params.append(app)
    query += " GROUP BY c.app, c.chat_id ORDER BY c.last_activity DESC, c.updated_at DESC;"
    return conn.execute(query, params).fetchall()


def get_messages(conn: sqlite3.Connection, chat_id: str, app: Optional[str] = None, limit: int = 50) -> List[sqlite3.Row]:
    query = "SELECT * FROM messages WHERE chat_id = ?"
    params = [chat_id]
    if app:
        query += " AND app = ?"
        params.append(app)
    query += " ORDER BY time DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return list(reversed(rows))


def get_pending_messages(conn: sqlite3.Connection, app: Optional[str] = None, limit: int = 50) -> List[sqlite3.Row]:
    query = """
        SELECT m.*, c.title as chat_title, c.category as chat_category
        FROM messages m
        JOIN chats c ON m.app = c.app AND m.chat_id = c.chat_id
        WHERE m.reviewed = 0
    """
    params = []
    if app:
        query += " AND m.app = ?"
        params.append(app)
    query += " ORDER BY m.time ASC LIMIT ?"
    params.append(limit)
    return conn.execute(query, params).fetchall()


def acknowledge_messages(
    conn: sqlite3.Connection,
    app: Optional[str] = None,
    mids: Optional[List[str]] = None,
    all_pending: bool = False,
) -> int:
    with conn:
        if all_pending:
            if app:
                cursor = conn.execute("UPDATE messages SET reviewed = 1 WHERE app = ? AND reviewed = 0;", (app,))
            else:
                cursor = conn.execute("UPDATE messages SET reviewed = 1 WHERE reviewed = 0;")
            return cursor.rowcount
        elif mids:
            placeholders = ",".join("?" for _ in mids)
            if app:
                cursor = conn.execute(f"UPDATE messages SET reviewed = 1 WHERE app = ? AND mid IN ({placeholders});", [app, *mids])
            else:
                cursor = conn.execute(f"UPDATE messages SET reviewed = 1 WHERE mid IN ({placeholders});", mids)
            return cursor.rowcount
    return 0


def search_fts(conn: sqlite3.Connection, query: str, app: Optional[str] = None, limit: int = 20) -> List[sqlite3.Row]:
    fts_expr = clean_fts_query(query)
    if not fts_expr:
        return []

    sql = """
        SELECT m.*, c.title as chat_title, snippet(messages_fts, -1, '<b>', '</b>', '...', 15) as matched_snippet,
               bm25(messages_fts) as rank
        FROM messages_fts f
        JOIN messages m ON f.app = m.app AND f.mid = m.mid
        JOIN chats c ON m.app = c.app AND m.chat_id = c.chat_id
        WHERE messages_fts MATCH ?
    """
    params = [fts_expr]
    if app:
        sql += " AND m.app = ?"
        params.append(app)
    sql += " ORDER BY rank LIMIT ?;"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def export_markdown(conn: sqlite3.Connection, app: str, chat_id: str, output_path: Path) -> int:
    chat_row = conn.execute("SELECT * FROM chats WHERE app = ? AND chat_id = ?;", (app, chat_id)).fetchone()
    title = chat_row["title"] if chat_row else chat_id
    msgs = conn.execute("SELECT * FROM messages WHERE app = ? AND chat_id = ? ORDER BY time ASC;", (app, chat_id)).fetchall()

    lines = [
        f"# Chat Export: {title}",
        f"- Platform: {app.upper()}",
        f"- Chat ID: `{chat_id}`",
        f"- Total Messages: {len(msgs)}\n",
    ]
    for m in msgs:
        prefix = "**Me**" if m["is_mine"] else f"**{m['author']}**"
        lines.append(f"### {prefix} (`{m['time']}`)")
        lines.append(f"{m['text']}\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return len(msgs)

