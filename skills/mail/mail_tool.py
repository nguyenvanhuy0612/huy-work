#!/usr/bin/env python3
"""Unified Mail CLI tool for Outlook Web and Gmail."""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills.common.safety import guard_outbound
from skills.common.storage import get_db_connection
from skills.mail.adapters.gmail import (
    DEFAULT_GMAIL_ACCOUNT,
    compose_gmail_email,
    find_gmail_tab,
    harvest_gmail_threads,
    list_gmail_accounts,
)
from skills.mail.adapters.outlook import (
    compose_outlook_email,
    find_outlook_tab,
    harvest_outlook_emails,
    read_active_reading_pane,
)
from skills.mail.mail_db import (
    acknowledge_emails,
    get_default_db_path,
    get_email_by_id,
    get_emails,
    get_pending_emails,
    init_db,
    search_fts,
    upsert_email,
)


def cmd_accounts(args: argparse.Namespace) -> int:
    """Lists detected open email accounts across browser tabs."""
    try:
        gmail_accs = list_gmail_accounts()
    except Exception as err:
        print(f"Warning: Could not query Gmail tabs ({err})", file=sys.stderr)
        gmail_accs = []

    outlook_tab = None
    try:
        outlook_tab = find_outlook_tab()
    except Exception:
        pass

    print(f"{'APP':<8} | {'STATUS':<8} | {'ACCOUNT / IDENTIFIER':<35} | {'TITLE'}")
    print("-" * 80)
    for g in gmail_accs:
        status = "[ACTIVE]" if g.get("active") else "[OPEN]"
        acc = g.get("account") or "Unknown Account"
        print(f"{'GMAIL':<8} | {status:<8} | {acc:<35} | {g.get('title')[:25]}")

    if outlook_tab:
        status = "[ACTIVE]" if outlook_tab.get("active") else "[OPEN]"
        print(f"{'OUTLOOK':<8} | {status:<8} | {'Corporate / Default':<35} | {outlook_tab.get('title')[:25]}")
    elif not gmail_accs:
        print("No open mail tabs (Gmail/Outlook) found in browser.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    db_path = Path(args.db) if args.db else get_default_db_path()
    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        emails = get_emails(conn, app=args.app, account=args.account, limit=args.limit, unread_only=args.unread)
        if not emails:
            print("No emails found in database matching criteria. Run 'sync' first.")
            return 0

        header = f"{'APP':<8} | {'STATUS':<8} | {'SENDER':<25} | {'DATE':<15} | {'SUBJECT'}"
        print(header)
        print("-" * len(header))
        for e in emails:
            status = "[UNREAD]" if not e["is_read"] else "[READ]"
            sender = e["sender"][:23] if e["sender"] else "Unknown"
            date_str = (e["timestamp"] or "")[:13]
            subject = e["subject"][:40] if e["subject"] else "(No Subject)"
            print(f"{e['app'].upper():<8} | {status:<8} | {sender:<25} | {date_str:<15} | {subject}")
        return 0
    finally:
        conn.close()


def cmd_read(args: argparse.Namespace) -> int:
    db_path = Path(args.db) if args.db else get_default_db_path()
    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        row = get_email_by_id(conn, args.id, app=args.app, account=args.account)
        if not row:
            print(f"Email with ID '{args.id}' not found in database.", file=sys.stderr)
            return 1

        print("=" * 80)
        print(f"Platform: {row['app'].upper()} | Account: {row['account']}")
        print(f"From    : {row['sender']}")
        print(f"Date    : {row['timestamp']}")
        print(f"Subject : {row['subject']}")
        print(f"Status  : {'Read' if row['is_read'] else 'Unread'} | Reviewed: {'Yes' if row['reviewed'] else 'No'}")
        print("-" * 80)
        body = row["body"] or row["snippet"] or "(No body content)"
        print(body)
        print("=" * 80)
        return 0
    finally:
        conn.close()


def cmd_search(args: argparse.Namespace) -> int:
    db_path = Path(args.db) if args.db else get_default_db_path()
    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        results = search_fts(conn, args.query, app=args.app, account=args.account, limit=args.limit)
        if not results:
            print(f"No email matches found for '{args.query}'.")
            return 0

        print(f"Found {len(results)} matches for '{args.query}':\n")
        for r in results:
            print(f"[{r['app'].upper()}] [{r['timestamp']}] {r['sender']}:")
            print(f"  Subject: {r['subject']}")
            print(f"  Snippet: {r['matched_snippet']}\n")
        return 0
    finally:
        conn.close()


def cmd_pending(args: argparse.Namespace) -> int:
    db_path = Path(args.db) if args.db else get_default_db_path()
    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        pending = get_pending_emails(conn, app=args.app, account=args.account, limit=args.limit)
        if not pending:
            print("No pending unreviewed emails found.")
            return 0

        print(f"Found {len(pending)} pending emails requiring review:\n")
        for p in pending:
            print(f"- [{p['app'].upper()}] [{p['timestamp']}] From: {p['sender']}")
            print(f"  Subject: {p['subject']} (ID: {p['email_id']})")
            if p["snippet"]:
                print(f"  Preview: {p['snippet'][:100]}...")
            print()
        return 0
    finally:
        conn.close()


def cmd_ack(args: argparse.Namespace) -> int:
    if not args.all and not args.ids:
        print("Error: Specify either --all or --ids <id...>", file=sys.stderr)
        return 1

    db_path = Path(args.db) if args.db else get_default_db_path()
    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        count = acknowledge_emails(conn, app=args.app, account=args.account, email_ids=args.ids, all_pending=args.all)
        print(f"Acknowledged {count} emails as reviewed.")
        return 0
    finally:
        conn.close()


def cmd_sync(args: argparse.Namespace) -> int:
    if not args.app:
        print("Error: --app [outlook|gmail] is required for 'sync'.", file=sys.stderr)
        return 1

    db_path = Path(args.db) if args.db else get_default_db_path()
    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        if args.app == "outlook":
            tab = find_outlook_tab()
            if not tab:
                print("Error: No open Outlook Web tab found in browser.", file=sys.stderr)
                return 1
            emails = harvest_outlook_emails(tab["id"], max_items=args.limit)
            account_id = args.account or "outlook_work"
            new_count = 0
            for e in emails:
                is_new = upsert_email(
                    conn,
                    app="outlook",
                    account=account_id,
                    email_id=e["email_id"],
                    conversation_id=e.get("conversation_id", ""),
                    sender=e["sender"],
                    subject=e["subject"],
                    snippet=e.get("snippet", ""),
                    timestamp=e.get("timestamp", ""),
                    is_read=e.get("is_read", False),
                )
                if is_new:
                    new_count += 1
            print(f"Synced Outlook: {len(emails)} emails harvested, {new_count} newly inserted.")
            return 0

        elif args.app == "gmail":
            target_acc = args.account or DEFAULT_GMAIL_ACCOUNT
            tab = find_gmail_tab(account=target_acc)
            if not tab:
                print(f"Error: No open Gmail tab found for account '{target_acc}'. Use 'accounts' to list open tabs.", file=sys.stderr)
                return 1

            # Ingest threads across categories
            cat = getattr(args, "category", "all")
            threads = harvest_gmail_threads(tab["id"], max_items=args.limit, category=cat)
            new_count = 0
            for t in threads:
                is_new = upsert_email(
                    conn,
                    app="gmail",
                    account=target_acc,
                    email_id=t["email_id"],
                    conversation_id=t.get("conversation_id", ""),
                    sender=t["sender"],
                    subject=t["subject"],
                    snippet=t.get("snippet", ""),
                    timestamp=t.get("timestamp", ""),
                    is_read=t.get("is_read", False),
                    category=t.get("category", "general"),
                )
                if is_new:
                    new_count += 1
            print(f"Synced Gmail ({target_acc}) [{cat.upper()}]: {len(threads)} threads harvested, {new_count} newly inserted.")
            return 0
        else:
            print(f"Unsupported app '{args.app}'.", file=sys.stderr)
            return 1
    finally:
        conn.close()


def cmd_draft(args: argparse.Namespace) -> int:
    """Creates a draft email in the compose window without sending."""
    if not args.app:
        print("Error: --app [outlook|gmail] is required for 'draft'.", file=sys.stderr)
        return 1

    try:
        if args.app == "outlook":
            tab = find_outlook_tab()
            if not tab:
                print("Error: Outlook tab not found.", file=sys.stderr)
                return 1
            res = compose_outlook_email(tab["id"], to=args.to, subject=args.subject, body=args.body, cc=args.cc, send_now=False)
            print(f"Draft created successfully in Outlook compose pane for: {args.to}")
            return 0

        elif args.app == "gmail":
            target_acc = args.account or DEFAULT_GMAIL_ACCOUNT
            tab = find_gmail_tab(account=target_acc)
            if not tab:
                print(f"Error: Gmail tab not found for account '{target_acc}'.", file=sys.stderr)
                return 1
            res = compose_gmail_email(tab["id"], to=args.to, subject=args.subject, body=args.body, cc=args.cc, send_now=False)
            print(f"Draft created successfully in Gmail compose pane ({target_acc}) for: {args.to}")
            return 0
        return 1
    except Exception as err:
        print(f"Error: Failed to create draft: {err}", file=sys.stderr)
        return 1


def cmd_send(args: argparse.Namespace) -> int:
    """Dispatches outbound email with safety guardrail."""
    if not args.app:
        print("Error: --app [outlook|gmail] is required for 'send'.", file=sys.stderr)
        return 1

    target_acc = args.account or (DEFAULT_GMAIL_ACCOUNT if args.app == "gmail" else "outlook_work")

    # Safety Guard: requires --confirm
    allowed = guard_outbound(
        confirmed=args.confirm,
        service=f"{args.app} ({target_acc})",
        action="Send Email (Permanent Outbound)",
        target=args.to,
        subject=args.subject,
        body=args.body,
        extra={"Cc": args.cc} if args.cc else None,
    )
    if not allowed:
        return 0

    try:
        if args.app == "outlook":
            tab = find_outlook_tab()
            if not tab:
                print("Error: Outlook tab not found.", file=sys.stderr)
                return 1
            res = compose_outlook_email(tab["id"], to=args.to, subject=args.subject, body=args.body, cc=args.cc, send_now=True)
            print(f"Successfully sent email via Outlook to: {args.to}")
            return 0

        elif args.app == "gmail":
            tab = find_gmail_tab(account=target_acc)
            if not tab:
                print(f"Error: Gmail tab not found for account '{target_acc}'.", file=sys.stderr)
                return 1
            res = compose_gmail_email(tab["id"], to=args.to, subject=args.subject, body=args.body, cc=args.cc, send_now=True)
            print(f"Successfully sent email via Gmail ({target_acc}) to: {args.to}")
            return 0
        return 1
    except Exception as err:
        print(f"Error: Failed to send email: {err}", file=sys.stderr)
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Unified Mail CLI for Outlook Web & Gmail")
    parser.add_argument("--app", choices=["outlook", "gmail"], help="Target mail service")
    parser.add_argument("--account", help="Target email account (e.g. nguyenvanhuy0612@gmail.com)")
    parser.add_argument("--db", help="Path to SQLite database")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # accounts
    p_acc = subparsers.add_parser("accounts", help="List open mail accounts across browser tabs")
    p_acc.set_defaults(func=cmd_accounts)

    # list
    p_list = subparsers.add_parser("list", help="List recent emails")
    p_list.add_argument("--limit", type=int, default=30, help="Max emails to display")
    p_list.add_argument("--unread", action="store_true", help="Filter unread only")
    p_list.set_defaults(func=cmd_list)

    # read
    p_read = subparsers.add_parser("read", help="Read email body and details")
    p_read.add_argument("--id", required=True, help="Email or conversation ID")
    p_read.set_defaults(func=cmd_read)

    # search
    p_search = subparsers.add_parser("search", help="Search emails via FTS5")
    p_search.add_argument("query", help="Search query string")
    p_search.add_argument("--limit", type=int, default=20, help="Max results")
    p_search.set_defaults(func=cmd_search)

    # pending
    p_pending = subparsers.add_parser("pending", help="List unreviewed emails")
    p_pending.add_argument("--limit", type=int, default=50, help="Max emails")
    p_pending.set_defaults(func=cmd_pending)

    # ack
    p_ack = subparsers.add_parser("ack", help="Mark emails as reviewed")
    p_ack.add_argument("--all", action="store_true", help="Acknowledge all pending")
    p_ack.add_argument("--ids", nargs="+", help="Specific email IDs")
    p_ack.set_defaults(func=cmd_ack)

    # sync
    p_sync = subparsers.add_parser("sync", help="Synchronize emails from active browser tab")
    p_sync.add_argument("--limit", type=int, default=50, help="Max emails to harvest")
    p_sync.add_argument("--category", choices=["all", "primary", "promotions", "social", "updates", "forums"], default="all", help="Category tab to sync (default: all)")
    p_sync.set_defaults(func=cmd_sync)

    # draft
    p_draft = subparsers.add_parser("draft", help="Create an email draft")
    p_draft.add_argument("--to", required=True, help="Recipient email address")
    p_draft.add_argument("--subject", required=True, help="Email subject line")
    p_draft.add_argument("--body", required=True, help="Email body content")
    p_draft.add_argument("--cc", help="Optional CC recipients")
    p_draft.set_defaults(func=cmd_draft)

    # send
    p_send = subparsers.add_parser("send", help="Send outbound email (requires --confirm)")
    p_send.add_argument("--to", required=True, help="Recipient email address")
    p_send.add_argument("--subject", required=True, help="Email subject line")
    p_send.add_argument("--body", required=True, help="Email body content")
    p_send.add_argument("--cc", help="Optional CC recipients")
    p_send.add_argument("--confirm", action="store_true", help="Confirm execution (bypasses dry-run preview)")
    p_send.set_defaults(func=cmd_send)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

