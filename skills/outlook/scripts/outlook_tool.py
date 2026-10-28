#!/usr/bin/env python3
"""Outlook Web CLI Tool for SQLite ingestion, querying, and summary workflows."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure script directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from bridge import (
        DEFAULT_BRIDGE_URL,
        call_bridge,
        find_outlook_tab,
        harvest_outlook_emails,
        read_active_reading_pane,
    )
    from db import (
        acknowledge_emails,
        get_db_connection,
        get_default_db_path,
        get_emails,
        get_pending_emails,
        init_db,
        search_fts,
        upsert_email,
    )
except ImportError:
    from .bridge import (
        DEFAULT_BRIDGE_URL,
        call_bridge,
        find_outlook_tab,
        harvest_outlook_emails,
        read_active_reading_pane,
    )
    from .db import (
        acknowledge_emails,
        get_db_connection,
        get_default_db_path,
        get_emails,
        get_pending_emails,
        init_db,
        search_fts,
        upsert_email,
    )


def cmd_list(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    init_db(conn)
    try:
        emails = get_emails(conn, limit=args.limit, unread_only=args.unread, category=args.category)
        if not emails:
            print("No emails found in database.")
            return 0

        print(f"{'SENDER':<25} | {'STATUS':<6} | {'TIMESTAMP':<15} | {'SUBJECT'}")
        print("-" * 90)
        for em in emails:
            sender = (em["sender"] or "Unknown")[:23]
            status = "Read" if em["is_read"] else "UNREAD"
            ts = (em["timestamp"] or "N/A")[:15]
            subject = (em["subject"] or "")[:40]
            print(f"{sender:<25} | {status:<6} | {ts:<15} | {subject}")
        return 0
    finally:
        conn.close()


def cmd_read(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    init_db(conn)
    try:
        results = search_fts(conn, args.id, limit=1)
        if not results:
            rows = conn.execute("SELECT * FROM emails WHERE email_id = ? OR conversation_id = ?", (args.id, args.id)).fetchall()
            if rows:
                results = rows
        if not results:
            print(f"Email not found matching identifier: {args.id}")
            return 1

        email = results[0]
        print("=" * 70)
        print(f"Subject   : {email['subject']}")
        print(f"Sender    : {email['sender']}")
        print(f"Timestamp : {email['timestamp']}")
        print(f"Read      : {'Yes' if email['is_read'] else 'No'}")
        print(f"Reviewed  : {'Yes' if email['reviewed'] else 'No'}")
        print("-" * 70)
        body = email["body"] or email["snippet"] or "(No body content cached)"
        print(body)
        print("=" * 70)
        return 0
    finally:
        conn.close()


def cmd_search(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    init_db(conn)
    try:
        results = search_fts(conn, args.query, limit=args.limit)
        if not results:
            print(f"No emails matched query: '{args.query}'")
            return 0

        print(f"Found {len(results)} matches for '{args.query}':")
        print("-" * 80)
        for em in results:
            print(f"[{em['timestamp']}] From: {em['sender']}")
            print(f"Subject: {em['subject']}")
            print(f"Snippet: {em['snippet']}")
            print("-" * 40)
        return 0
    finally:
        conn.close()


def cmd_pending(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    init_db(conn)
    try:
        pending = get_pending_emails(conn, limit=args.limit)
        if not pending:
            print("No pending unreviewed emails.")
            return 0

        print(f"{'SENDER':<25} | {'TIMESTAMP':<15} | {'SUBJECT'}")
        print("-" * 80)
        for em in pending:
            sender = (em["sender"] or "Unknown")[:23]
            ts = (em["timestamp"] or "N/A")[:15]
            subject = (em["subject"] or "")[:35]
            print(f"{sender:<25} | {ts:<15} | {subject}")
        return 0
    finally:
        conn.close()


def cmd_sync(args: argparse.Namespace) -> int:
    bridge_url = args.bridge or DEFAULT_BRIDGE_URL
    print(f"Searching for active Outlook Web tab via {bridge_url}...")
    tab = find_outlook_tab(bridge_url=bridge_url)
    if not tab:
        print("Error: No active Outlook Web tab found. Open Outlook Web (outlook.office.com) in Chrome.", file=sys.stderr)
        return 1

    tab_id = tab["id"]
    print(f"Found Outlook tab {tab_id}: {tab.get('title', '')[:50]}")
    raw_emails = harvest_outlook_emails(tab_id, max_items=args.limit, bridge_url=bridge_url)
    print(f"Harvested {len(raw_emails)} email entries from tab.")

    conn = get_db_connection(Path(args.db) if args.db else None)
    init_db(conn)
    try:
        inserted = 0
        for item in raw_emails:
            is_new = upsert_email(
                conn=conn,
                email_id=item["email_id"],
                conversation_id=item.get("conversation_id", ""),
                sender=item.get("sender", "Unknown"),
                subject=item.get("subject", ""),
                snippet=item.get("snippet", ""),
                timestamp=item.get("timestamp", ""),
                is_read=item.get("is_read", False),
                raw_data=item,
            )
            if is_new:
                inserted += 1
        print(f"Sync complete: {inserted} new emails recorded, {len(raw_emails) - inserted} updated.")
        return 0
    finally:
        conn.close()


def cmd_ack(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    init_db(conn)
    try:
        if args.all:
            count = acknowledge_emails(conn, all_pending=True)
            print(f"Acknowledged {count} pending emails as reviewed.")
        elif args.ids:
            count = acknowledge_emails(conn, email_ids=args.ids)
            print(f"Acknowledged {count} emails as reviewed.")
        else:
            print("Specify --all or --ids <id1> <id2>")
            return 1
        return 0
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Outlook Web Message Suite & Database CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_list = subparsers.add_parser("list", help="List recent emails")
    p_list.add_argument("--limit", type=int, default=30)
    p_list.add_argument("--unread", action="store_true", help="Filter unread only")
    p_list.add_argument("--category", default=None, help="Filter by category")
    p_list.add_argument("--db", default=None, help="Database path")

    p_read = subparsers.add_parser("read", help="Read full email or thread")
    p_read.add_argument("--id", required=True, help="Email ID, Conversation ID or search term")
    p_read.add_argument("--db", default=None, help="Database path")

    p_srch = subparsers.add_parser("search", help="Full-text search using SQLite FTS5")
    p_srch.add_argument("query", help="Search query")
    p_srch.add_argument("--limit", type=int, default=20)
    p_srch.add_argument("--db", default=None, help="Database path")

    p_pend = subparsers.add_parser("pending", help="List emails pending review")
    p_pend.add_argument("--limit", type=int, default=30)
    p_pend.add_argument("--db", default=None, help="Database path")

    p_sync = subparsers.add_parser("sync", help="Synchronize emails from active Outlook Web tab")
    p_sync.add_argument("--limit", type=int, default=50)
    p_sync.add_argument("--bridge", default=None, help="Browser bridge URL")
    p_sync.add_argument("--db", default=None, help="Database path")

    p_ack = subparsers.add_parser("ack", help="Mark emails as reviewed")
    p_ack.add_argument("--all", action="store_true", help="Acknowledge all pending")
    p_ack.add_argument("--ids", nargs="+", help="Specific email IDs to acknowledge")
    p_ack.add_argument("--db", default=None, help="Database path")

    args = parser.parse_args()

    handlers = {
        "list": cmd_list,
        "read": cmd_read,
        "search": cmd_search,
        "pending": cmd_pending,
        "sync": cmd_sync,
        "ack": cmd_ack,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
