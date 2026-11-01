"""SQLite storage layer for Mail domain (Outlook and Gmail)."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from skills.common.storage import clean_fts_query, get_db_connection


def get_default_db_path() -> Path:
    return Path(__file__).resolve().parent / "mail.db"


def init_db(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS emails (
                app TEXT NOT NULL,
                account TEXT NOT NULL,
                email_id TEXT NOT NULL,
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
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (app, account, email_id)
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_app_acc ON emails(app, account);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_reviewed ON emails(app, account, reviewed);")

        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
                app UNINDEXED,
                account UNINDEXED,
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
    app: str,
    account: str,
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
    """Upserts email into DB and synchronizes FTS5 virtual table."""
    raw_json = json.dumps(raw_data or {}, ensure_ascii=False)
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO emails (app, account, email_id, conversation_id, sender, subject, snippet, body, timestamp, is_read, category, raw_data, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(app, account, email_id) DO UPDATE SET
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
            (app, account, email_id, conversation_id, sender, subject, snippet, body, timestamp, 1 if is_read else 0, category, raw_json),
        )
        is_new = cursor.rowcount > 0

        # Update FTS index
        conn.execute("DELETE FROM emails_fts WHERE app = ? AND account = ? AND email_id = ?;", (app, account, email_id))
        conn.execute(
            """
            INSERT INTO emails_fts (app, account, email_id, sender, subject, snippet, body)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (app, account, email_id, sender, subject, snippet, body),
        )
        return is_new


def get_emails(
    conn: sqlite3.Connection,
    app: Optional[str] = None,
    account: Optional[str] = None,
    limit: int = 50,
    unread_only: bool = False,
    category: Optional[str] = None,
) -> List[sqlite3.Row]:
    query = "SELECT * FROM emails WHERE 1=1"
    params = []
    if app:
        query += " AND app = ?"
        params.append(app)
    if account:
        query += " AND account = ?"
        params.append(account)
    if unread_only:
        query += " AND is_read = 0"
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY updated_at DESC, timestamp DESC LIMIT ?"
    params.append(limit)
    return conn.execute(query, params).fetchall()


def get_email_by_id(
    conn: sqlite3.Connection,
    email_id: str,
    app: Optional[str] = None,
    account: Optional[str] = None,
) -> Optional[sqlite3.Row]:
    query = "SELECT * FROM emails WHERE (email_id = ? OR conversation_id = ?)"
    params = [email_id, email_id]
    if app:
        query += " AND app = ?"
        params.append(app)
    if account:
        query += " AND account = ?"
        params.append(account)
    return conn.execute(query, params).fetchone()


def get_pending_emails(
    conn: sqlite3.Connection,
    app: Optional[str] = None,
    account: Optional[str] = None,
    limit: int = 50,
) -> List[sqlite3.Row]:
    query = "SELECT * FROM emails WHERE reviewed = 0"
    params = []
    if app:
        query += " AND app = ?"
        params.append(app)
    if account:
        query += " AND account = ?"
        params.append(account)
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    return conn.execute(query, params).fetchall()


def acknowledge_emails(
    conn: sqlite3.Connection,
    app: Optional[str] = None,
    account: Optional[str] = None,
    email_ids: Optional[List[str]] = None,
    all_pending: bool = False,
) -> int:
    with conn:
        if all_pending:
            query = "UPDATE emails SET reviewed = 1 WHERE reviewed = 0"
            params = []
            if app:
                query += " AND app = ?"
                params.append(app)
            if account:
                query += " AND account = ?"
                params.append(account)
            cursor = conn.execute(query, params)
            return cursor.rowcount
        elif email_ids:
            placeholders = ",".join("?" for _ in email_ids)
            query = f"UPDATE emails SET reviewed = 1 WHERE email_id IN ({placeholders})"
            params = list(email_ids)
            if app:
                query += " AND app = ?"
                params.append(app)
            if account:
                query += " AND account = ?"
                params.append(account)
            cursor = conn.execute(query, params)
            return cursor.rowcount
    return 0


def search_fts(
    conn: sqlite3.Connection,
    query: str,
    app: Optional[str] = None,
    account: Optional[str] = None,
    limit: int = 20,
) -> List[sqlite3.Row]:
    fts_expr = clean_fts_query(query)
    if not fts_expr:
        return []

    sql = """
        SELECT e.*, snippet(emails_fts, -1, '<b>', '</b>', '...', 15) as matched_snippet,
               bm25(emails_fts) as rank
        FROM emails_fts f
        JOIN emails e ON f.app = e.app AND f.account = e.account AND f.email_id = e.email_id
        WHERE emails_fts MATCH ?
    """
    params = [fts_expr]
    if app:
        sql += " AND e.app = ?"
        params.append(app)
    if account:
        sql += " AND e.account = ?"
        params.append(account)
    sql += " ORDER BY rank LIMIT ?;"
    params.append(limit)
    return conn.execute(sql, params).fetchall()

