#!/usr/bin/env python3
"""Unified Chat CLI tool for Microsoft Teams and Zalo Web."""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills.chat.adapters.teams import (
    fetch_teams_messages_direct,
    find_teams_tab,
    harvest_teams_auth,
    normalize_api_message,
    scan_sidebar_chats,
    send_teams_message_direct,
)
from skills.chat.adapters.zalo import (
    find_zalo_tab,
    harvest_active_messages,
    harvest_conversations,
    send_zalo_message,
)
from skills.chat.chat_db import (
    acknowledge_messages,
    classify_chat_type,
    export_markdown,
    get_chats,
    get_default_db_path,
    get_messages,
    get_pending_messages,
    init_db,
    insert_messages_batch,
    search_fts,
    upsert_chat,
)
from skills.common.safety import guard_outbound
from skills.common.storage import get_db_connection


def resolve_chat_target(conn, app: str, chat_query: str) -> Optional[Dict[str, Any]]:
    """Resolves chat by exact ID or case-insensitive title match."""
    row = conn.execute("SELECT * FROM chats WHERE app = ? AND chat_id = ?;", (app, chat_query)).fetchone()
    if row:
        return dict(row)

    rows = conn.execute(
        "SELECT * FROM chats WHERE app = ? AND LOWER(title) LIKE ?;",
        (app, f"%{chat_query.lower()}%"),
    ).fetchall()
    if len(rows) == 1:
        return dict(rows[0])
    if len(rows) > 1:
        exact = [r for r in rows if r["title"].lower() == chat_query.lower()]
        if len(exact) == 1:
            return dict(exact[0])
        print(f"Ambiguous chat query '{chat_query}' matches {len(rows)} chats. Please specify exact chat ID.", file=sys.stderr)
        return None
    return None


def cmd_chats(args: argparse.Namespace) -> int:
    db_path = Path(args.db) if args.db else get_default_db_path()
    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        chats = get_chats(conn, app=args.app)
        if not chats:
            filter_str = f" for '{args.app}'" if args.app else ""
            print(f"No chats found in database{filter_str}. Run 'sync' first.")
            return 0

        header = f"{'APP':<6} | {'TITLE':<40} | {'TYPE':<8} | {'TOTAL':<6} | {'PENDING':<8} | {'LAST ACTIVITY'}"
        print(header)
        print("-" * len(header))
        for c in chats:
            title = c["title"][:38] if c["title"] else "Untitled"
            last_act = c["last_activity"] or "N/A"
            print(f"{c['app'].upper():<6} | {title:<40} | {c['category']:<8} | {c['total_messages']:<6} | {c['pending_count']:<8} | {last_act}")
        return 0
    finally:
        conn.close()


def cmd_log(args: argparse.Namespace) -> int:
    if not args.app:
        print("Error: --app [teams|zalo] is required for 'log'.", file=sys.stderr)
        return 1

    db_path = Path(args.db) if args.db else get_default_db_path()
    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        target = resolve_chat_target(conn, args.app, args.chat)
        if not target:
            print(f"Chat '{args.chat}' not found in database for app '{args.app}'.", file=sys.stderr)
            return 1

        msgs = get_messages(conn, target["chat_id"], app=args.app, limit=args.limit)
        if not msgs:
            print(f"No messages recorded for '{target['title']}'.")
            return 0

        print(f"--- Log for {target['title']} ({target['chat_id']}) [{args.app.upper()}] ---")
        for m in msgs:
            prefix = "[Me]" if m["is_mine"] else f"[{m['author']}]"
            rev = "" if m["reviewed"] else " [UNREVIEWED]"
            print(f"{prefix} ({m['time']}){rev}:")
            print(f"  {m['text']}\n")
        return 0
    finally:
        conn.close()


def cmd_search(args: argparse.Namespace) -> int:
    db_path = Path(args.db) if args.db else get_default_db_path()
    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        results = search_fts(conn, args.query, app=args.app, limit=args.limit)
        if not results:
            print(f"No matches found for '{args.query}'.")
            return 0

        print(f"Found {len(results)} matches for '{args.query}':\n")
        for r in results:
            print(f"[{r['app'].upper()}] [{r['time']}] {r['author']} in '{r['chat_title']}':")
            print(f"  {r['matched_snippet']}\n")
        return 0
    finally:
        conn.close()


def cmd_pending(args: argparse.Namespace) -> int:
    db_path = Path(args.db) if args.db else get_default_db_path()
    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        pending = get_pending_messages(conn, app=args.app, limit=args.limit)
        if not pending:
            print("No pending unreviewed messages found.")
            return 0

        # Group by app and chat
        grouped: Dict[str, List[Any]] = {}
        for p in pending:
            key = f"[{p['app'].upper()}] {p['chat_title']}"
            grouped.setdefault(key, []).append(p)

        print(f"Found {len(pending)} pending messages across chats:\n")
        for title, msgs in grouped.items():
            print(f"=== {title} ({len(msgs)} new messages) ===")
            for m in msgs:
                print(f"  [{m['time']}] {m['author']}: {m['text']}")
            print()
        return 0
    finally:
        conn.close()


def cmd_ack(args: argparse.Namespace) -> int:
    if not args.all and not args.ids:
        print("Error: Specify either --all or --ids <mid...>", file=sys.stderr)
        return 1

    db_path = Path(args.db) if args.db else get_default_db_path()
    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        count = acknowledge_messages(conn, app=args.app, mids=args.ids, all_pending=args.all)
        print(f"Acknowledged {count} messages as reviewed.")
        return 0
    finally:
        conn.close()


def cmd_sync(args: argparse.Namespace) -> int:
    if not args.app:
        print("Error: --app [teams|zalo] is required for 'sync'.", file=sys.stderr)
        return 1

    db_path = Path(args.db) if args.db else get_default_db_path()
    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        if args.app == "teams":
            tab = find_teams_tab()
            if not tab:
                print("Error: No open Microsoft Teams tab found in browser.", file=sys.stderr)
                return 1
            auth = harvest_teams_auth(tab["id"])
            chats = scan_sidebar_chats(tab["id"])
            for c in chats:
                cid = c["chatId"]
                cat = classify_chat_type(cid)
                upsert_chat(conn, "teams", cid, c["title"], category=cat)

            target_chats = [args.chat] if args.chat else [c["chatId"] for c in chats[:15]]
            total_new = 0
            for cid in target_chats:
                try:
                    res = fetch_teams_messages_direct(auth, cid)
                    norm_msgs = []
                    for m in res.get("messages", []):
                        norm = normalize_api_message(m, auth.get("selfId", ""), cid)
                        if norm:
                            norm_msgs.append(norm)
                    inserted = insert_messages_batch(conn, "teams", norm_msgs)
                    total_new += inserted
                except Exception as err:
                    print(f"Warning: Failed to fetch messages for Teams chat {cid}: {err}", file=sys.stderr)
            print(f"Synced Teams: {len(chats)} chats scanned, {total_new} new messages inserted.")
            return 0

        elif args.app == "zalo":
            tab = find_zalo_tab()
            if not tab:
                print("Error: No open Zalo tab found in browser.", file=sys.stderr)
                return 1
            user_info, convs = harvest_conversations(tab["id"])
            for c in convs:
                cid = c["chat_id"]
                cat = "group" if c.get("is_group") else "direct"
                upsert_chat(conn, "zalo", cid, c["title"], category=cat, last_activity=c.get("last_activity"))
                last_m = c.get("last_message")
                if last_m and last_m.get("text"):
                    norm = {
                        "mid": last_m.get("msg_id") or last_m.get("cli_msg_id"),
                        "chat_id": cid,
                        "author": last_m.get("author") or "Unknown",
                        "is_mine": last_m.get("is_mine", False),
                        "time": last_m.get("time") or "",
                        "text": last_m.get("text") or "",
                    }
                    insert_messages_batch(conn, "zalo", [norm])

            # Ingest active open chat
            active_msgs = harvest_active_messages(tab["id"])
            inserted = insert_messages_batch(conn, "zalo", active_msgs)
            print(f"Synced Zalo: {len(convs)} conversations scanned, {inserted} active messages inserted.")
            return 0
        else:
            print(f"Unsupported app '{args.app}'.", file=sys.stderr)
            return 1
    finally:
        conn.close()


def cmd_send(args: argparse.Namespace) -> int:
    if not args.app:
        print("Error: --app [teams|zalo] is required for 'send'.", file=sys.stderr)
        return 1

    db_path = Path(args.db) if args.db else get_default_db_path()
    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        target = resolve_chat_target(conn, args.app, args.chat)
        chat_id = target["chat_id"] if target else args.chat
        target_name = target["title"] if target else args.chat

        # Safety Guard: requires --confirm
        allowed = guard_outbound(
            confirmed=args.confirm,
            service=args.app,
            action="Send Chat Message",
            target=f"{target_name} ({chat_id})",
            body=args.message,
        )
        if not allowed:
            return 0

        # Execute send
        try:
            if args.app == "teams":
                tab = find_teams_tab()
                if not tab:
                    print("Error: Teams tab not found.", file=sys.stderr)
                    return 1
                auth = harvest_teams_auth(tab["id"])
                res = send_teams_message_direct(auth, chat_id, args.message)
                print(f"Successfully sent message to Teams chat '{target_name}'.")
                return 0
            elif args.app == "zalo":
                tab = find_zalo_tab()
                if not tab:
                    print("Error: Zalo tab not found.", file=sys.stderr)
                    return 1
                res = send_zalo_message(tab["id"], chat_id, args.message)
                print(f"Successfully sent message to Zalo chat '{target_name}'.")
                return 0
            return 0
        except Exception as err:
            print(f"Error: Failed to send {args.app} message: {err}", file=sys.stderr)
            return 1
    finally:
        conn.close()


def cmd_export(args: argparse.Namespace) -> int:
    if not args.app:
        print("Error: --app [teams|zalo] is required for 'export'.", file=sys.stderr)
        return 1

    db_path = Path(args.db) if args.db else get_default_db_path()
    conn = get_db_connection(db_path)
    try:
        init_db(conn)
        target = resolve_chat_target(conn, args.app, args.chat)
        if not target:
            print(f"Chat '{args.chat}' not found in database.", file=sys.stderr)
            return 1

        out_path = Path(args.output) if args.output else Path(f"export_{args.app}_{target['chat_id']}.md")
        count = export_markdown(conn, args.app, target["chat_id"], out_path)
        print(f"Exported {count} messages to {out_path}")
        return 0
    finally:
        conn.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Unified Chat CLI for Microsoft Teams & Zalo")
    parser.add_argument("--app", choices=["teams", "zalo"], help="Filter or target specific platform")
    parser.add_argument("--db", help="Path to SQLite database")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list / chats
    p_chats = subparsers.add_parser("list", aliases=["chats"], help="List conversations and pending counts")
    p_chats.set_defaults(func=cmd_chats)

    # log
    p_log = subparsers.add_parser("log", help="Display chat messages")
    p_log.add_argument("--chat", required=True, help="Chat ID or title substring")
    p_log.add_argument("--limit", type=int, default=20, help="Max messages to fetch")
    p_log.set_defaults(func=cmd_log)

    # search
    p_search = subparsers.add_parser("search", help="Search messages via FTS5")
    p_search.add_argument("query", help="Search query string")
    p_search.add_argument("--limit", type=int, default=20, help="Max results")
    p_search.set_defaults(func=cmd_search)

    # pending
    p_pending = subparsers.add_parser("pending", help="List unreviewed messages")
    p_pending.add_argument("--limit", type=int, default=50, help="Max messages")
    p_pending.set_defaults(func=cmd_pending)

    # ack
    p_ack = subparsers.add_parser("ack", help="Mark messages as reviewed")
    p_ack.add_argument("--all", action="store_true", help="Acknowledge all pending")
    p_ack.add_argument("--ids", nargs="+", help="Specific message IDs")
    p_ack.set_defaults(func=cmd_ack)

    # sync
    p_sync = subparsers.add_parser("sync", help="Synchronize conversations from browser tab")
    p_sync.add_argument("--chat", help="Specific chat ID to sync")
    p_sync.set_defaults(func=cmd_sync)

    # send
    p_send = subparsers.add_parser("send", help="Send outbound message (requires --confirm)")
    p_send.add_argument("--chat", required=True, help="Target chat ID or title")
    p_send.add_argument("--message", required=True, help="Message text")
    p_send.add_argument("--confirm", action="store_true", help="Confirm execution (bypasses dry-run preview)")
    p_send.set_defaults(func=cmd_send)

    # export
    p_export = subparsers.add_parser("export", help="Export chat log to markdown")
    p_export.add_argument("--chat", required=True, help="Target chat ID or title")
    p_export.add_argument("--output", help="Output markdown path")
    p_export.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

