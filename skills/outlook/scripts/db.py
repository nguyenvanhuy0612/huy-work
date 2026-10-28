"""SQLite storage layer for Outlook Web emails and thread metadata."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_default_db_path() -> Path:
    return Path(__file__).resolve().parent / "outlook.db"


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
            CREATE TABLE IF NOT EXISTS emails (
                email_id TEXT PRIMARY KEY,
                conversation_id TEXT,
                sender TEXT NOT NULL,
                subject TEXT NOT NULL,
                snippet TEXT,
                body TEXT,
                timestamp TEXT,
                is_read INTEGER DEFAULT 0,
                reviewed INTEGER DEFAULT 0,
                category TEXT DEFAULT 'general',
                raw_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_conv ON emails(conversation_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_reviewed ON emails(reviewed);")

        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
                email_id UNINDEXED,
                sender,
                subject,
                snippet,
                body,
                tokenize = 'unicode61'
            );
        """)


def upsert_email(
    conn: sqlite3.Connection,
    email_id: str,
    conversation_id: str,
    sender: str,
    subject: str,
    snippet: str = "",
    body: str = "",
    timestamp: str = "",
    is_read: bool = False,
    category: str = "general",
    raw_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Upserts email and updates FTS index. Returns True if inserted, False if updated."""
    raw_json = json.dumps(raw_data or {}, ensure_ascii=False)
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO emails (email_id, conversation_id, sender, subject, snippet, body, timestamp, is_read, category, raw_data, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(email_id) DO UPDATE SET
                conversation_id = excluded.conversation_id,
                sender = excluded.sender,
                subject = excluded.subject,
                snippet = COALESCE(NULLIF(excluded.snippet, ''), emails.snippet),
                body = COALESCE(NULLIF(excluded.body, ''), emails.body),
                timestamp = COALESCE(NULLIF(excluded.timestamp, ''), emails.timestamp),
                is_read = excluded.is_read,
                category = excluded.category,
                raw_data = excluded.raw_data,
                updated_at = CURRENT_TIMESTAMP;
            """,
            (email_id, conversation_id, sender, subject, snippet, body, timestamp, 1 if is_read else 0, category, raw_json),
        )
        is_new = cursor.rowcount > 0

        # Sync FTS
        conn.execute("DELETE FROM emails_fts WHERE email_id = ?;", (email_id,))
        conn.execute(
            """
            INSERT INTO emails_fts (email_id, sender, subject, snippet, body)
            VALUES (?, ?, ?, ?, ?);
            """,
            (email_id, sender, subject, snippet, body),
        )
        return is_new


def get_emails(
    conn: sqlite3.Connection,
    limit: int = 50,
    unread_only: bool = False,
    category: Optional[str] = None,
) -> List[sqlite3.Row]:
    query = "SELECT * FROM emails WHERE 1=1"
    params = []
    if unread_only:
        query += " AND is_read = 0"
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY updated_at DESC, timestamp DESC LIMIT ?"
    params.append(limit)
    return conn.execute(query, params).fetchall()


def get_pending_emails(conn: sqlite3.Connection, limit: int = 50) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM emails WHERE reviewed = 0 ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()


def acknowledge_emails(conn: sqlite3.Connection, email_ids: Optional[List[str]] = None, all_pending: bool = False) -> int:
    with conn:
        if all_pending:
            cursor = conn.execute("UPDATE emails SET reviewed = 1 WHERE reviewed = 0;")
            return cursor.rowcount
        elif email_ids:
            placeholders = ",".join("?" for _ in email_ids)
            cursor = conn.execute(f"UPDATE emails SET reviewed = 1 WHERE email_id IN ({placeholders});", email_ids)
            return cursor.rowcount
    return 0


def search_fts(conn: sqlite3.Connection, query: str, limit: int = 20) -> List[sqlite3.Row]:
    clean_query = "".join(c for c in query if c.isalnum() or c in (" ", "_", "-")).strip()
    if not clean_query:
        return []
    terms = clean_query.split()
    fts_expr = " AND ".join(f'"{t}"*' for t in terms)
    return conn.execute(
        """
        SELECT e.*, bm25(emails_fts) as rank
        FROM emails_fts f
        JOIN emails e ON f.email_id = e.email_id
        WHERE emails_fts MATCH ?
        ORDER BY rank
        LIMIT ?;
        """,
        (fts_expr, limit),
    ).fetchall()
