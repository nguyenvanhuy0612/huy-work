"""Base SQLite storage manager with WAL mode and FTS5 full-text indexing."""

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_db_connection(db_path: Path, timeout: float = 10.0) -> sqlite3.Connection:
    """Creates a configured SQLite connection with WAL mode and sensible timeouts."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def clean_fts_query(query: str) -> str:
    """Sanitizes user input into a safe FTS5 query string with prefix matching."""
    cleaned = "".join(c for c in query if c.isalnum() or c in (" ", "_", "-")).strip()
    if not cleaned:
        return ""
    terms = cleaned.split()
    return " AND ".join(f'"{t}"*' for t in terms)


class BaseStorage:
    """Base storage wrapper offering database lifecycle and indexing helpers."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def get_connection(self) -> sqlite3.Connection:
        return get_db_connection(self.db_path)

