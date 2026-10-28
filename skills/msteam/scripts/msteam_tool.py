#!/usr/bin/env python3
"""Microsoft Teams CLI Tool for SQLite ingestion, querying, and summary workflows."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure script directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from bridge import (
        DEFAULT_BRIDGE_URL,
        fetch_api_messages,
        fetch_teams_messages_direct,
        find_teams_tab,
        harvest_teams_auth,
        normalize_api_message,
        scan_sidebar_chats,
    )
    from db import (
        acknowledge_messages,
        classify_chat_type,
        get_chat_latest_message_info,
        get_chat_sync_cursor,
        get_chats,
        get_db_connection,
        get_default_db_path,
        get_messages,
        get_pending_messages,
        init_db,
        insert_message,
        migrate_from_json,
        search_fts,
        upsert_chat,
    )
except ImportError:
    from .bridge import (
        DEFAULT_BRIDGE_URL,
        fetch_api_messages,
        fetch_teams_messages_direct,
        find_teams_tab,
        harvest_teams_auth,
        normalize_api_message,
        scan_sidebar_chats,
    )
    from .db import (
        acknowledge_messages,
        classify_chat_type,
        get_chat_latest_message_info,
        get_chat_sync_cursor,
        get_chats,
        get_db_connection,
        get_default_db_path,
        get_messages,
        get_pending_messages,
        init_db,
        insert_message,
        migrate_from_json,
        search_fts,
        upsert_chat,
    )


def cmd_migrate(args: argparse.Namespace) -> int:
    source_json = Path(args.source)
    target_db = Path(args.db) if args.db else get_default_db_path()
    if not source_json.exists():
        print(f"Error: Source JSON file does not exist: {source_json}", file=sys.stderr)
        return 1
    chats_count, msgs_count = migrate_from_json(source_json, target_db)
    print(f"Successfully migrated {chats_count} chats and {msgs_count} messages into {target_db}")
    return 0


def cmd_chats(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    try:
        chats = get_chats(conn)
        if not chats:
            print("No chats found in database.")
            return 0

        print(f"{'TITLE':<45} | {'TYPE':<8} | {'TOTAL':<6} | {'PENDING':<8} | {'LAST ACTIVITY'}")
        print("-" * 105)
        for c in chats:
            title = c["title"][:43] + ".." if len(c["title"]) > 45 else c["title"]
            print(f"{title:<45} | {c['type']:<8} | {c['total_messages']:<6} | {c['unreviewed_messages']:<8} | {c['last_activity'] or 'N/A'}")
        return 0
    finally:
        conn.close()


def cmd_log(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    try:
        messages = get_messages(
            conn,
            chat_id=args.chat,
            limit=args.limit,
            offset=args.offset,
            author=args.author,
            search=args.search,
        )
        if not messages:
            print("No messages found matching criteria.")
            return 0

        # Display chronologically
        for m in reversed(messages):
            author = m["author"]
            prefix = f"[{m['time']}] {author} ({m['chat_title']}):"
            print(f"\033[1;36m{prefix}\033[0m")
            for line in (m["text"] or "").splitlines():
                print(f"  {line}")
            raw = json.loads(m["raw_json"] or "{}")
            if raw.get("attachments"):
                print(f"  \033[2m[Attachments: {', '.join(raw['attachments']) if isinstance(raw['attachments'], list) else raw['attachments']}]\033[0m")
            if raw.get("reactions"):
                print(f"  \033[2m[Reactions: {', '.join(raw['reactions']) if isinstance(raw['reactions'], list) else raw['reactions']}]\033[0m")
            print()
        return 0
    finally:
        conn.close()


def cmd_search(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    try:
        results = search_fts(conn, args.query, limit=args.limit)
        if not results:
            print(f"No messages matched query: {args.query}")
            return 0

        print(f"Found {len(results)} matches for '{args.query}':\n")
        for r in results:
            print(f"[{r['time']}] {r['author']} in '{r['chat_title']}':")
            snippet = r["highlighted_snippet"] or r["text"]
            print(f"  {snippet}\n")
        return 0
    finally:
        conn.close()


def cmd_pending(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    try:
        pending = get_pending_messages(conn, chat_id=args.chat)
        if not pending:
            print("No pending messages requiring review.")
            return 0

        print(f"Found {len(pending)} pending messages across chats:\n")
        by_chat: Dict[str, List[Any]] = {}
        for m in pending:
            by_chat.setdefault(m["chat_title"], []).append(m)

        for chat_title, msgs in by_chat.items():
            print(f"=== {chat_title} ({len(msgs)} new messages) ===")
            for m in msgs:
                print(f"  [{m['time']}] {m['author']}: {m['text'][:120]}")
            print()
        return 0
    finally:
        conn.close()


def cmd_ack(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    try:
        if args.all:
            pending = get_pending_messages(conn)
            ids = [m["id"] for m in pending]
        else:
            ids = args.ids
        count = acknowledge_messages(conn, ids)
        print(f"Acknowledged {count} messages as reviewed.")
        return 0
    finally:
        conn.close()


def cmd_export(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    try:
        messages = get_messages(conn, chat_id=args.chat, limit=args.limit)

        output_path = Path(args.output) if args.output else None

        if args.format == "json":
            data = [dict(m) for m in messages]
            rendered = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            # Markdown export
            lines = [f"# Teams Export: {args.chat or 'All Chats'}\n"]
            for m in reversed(messages):
                lines.append(f"### [{m['time']}] {m['author']} (`{m['chat_title']}`)")
                lines.append(f"{m['text']}\n")
            rendered = "\n".join(lines)

        if output_path:
            output_path.write_text(rendered, encoding="utf-8")
            print(f"Exported {len(messages)} messages to {output_path}")
        else:
            print(rendered)
        return 0
    finally:
        conn.close()


def cmd_sync(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    init_db(conn)

    bridge_url = args.bridge_url or DEFAULT_BRIDGE_URL
    try:
        tab = find_teams_tab(bridge_url)
    except Exception as err:
        print(f"Could not connect to browser bridge ({err}). Is Chrome running with the bridge?", file=sys.stderr)
        return 1

    if not tab:
        print("No active Microsoft Teams tab found in browser.", file=sys.stderr)
        return 1

    tab_id = tab["id"]
    print(f"Found Teams tab: ID {tab_id} - '{tab.get('title')}'")

    try:
        auth = harvest_teams_auth(tab_id, bridge_url=bridge_url)
    except Exception as err:
        print(f"Error harvesting Teams credentials: {err}", file=sys.stderr)
        return 1

    sidebar_chats = scan_sidebar_chats(tab_id, bridge_url=bridge_url)
    print(f"Discovered {len(sidebar_chats)} chats in sidebar. Credentials harvested; browser released.")

    target_chats = sidebar_chats
    if getattr(args, "chat", None):
        needle = args.chat.lower()
        target_chats = [
            c for c in sidebar_chats
            if needle == c.get("chatId", "").lower() or needle in c.get("title", "").lower()
        ]
        if not target_chats and ":" in args.chat:
            target_chats = [{"chatId": args.chat, "title": args.chat}]
        print(f"Filtered to {len(target_chats)} target chat(s) matching '{args.chat}'.")

    if getattr(args, "limit_chats", None) and args.limit_chats > 0:
        target_chats = target_chats[:args.limit_chats]

    max_pages = getattr(args, "max_pages", 1) or 1
    new_messages_count = 0
    total_requests_count = 0

    for chat in target_chats:
        chat_id = chat.get("chatId")
        title = chat.get("title")
        if not chat_id or not title:
            continue

        chat_type = classify_chat_type(chat_id)
        # Ensure chat record exists prior to message insertions to satisfy foreign key constraints
        upsert_chat(
            conn,
            chat_id=chat_id,
            title=title,
            chat_type=chat_type,
            last_scanned_at=datetime.now(timezone.utc).isoformat(),
        )

        latest_time, latest_mid = get_chat_latest_message_info(conn, chat_id)
        next_url = None
        sync_cursor = None

        for page in range(max_pages):
            try:
                total_requests_count += 1
                data = fetch_teams_messages_direct(auth, chat_id, next_url=next_url)
                self_id = data.get("selfId", "")
                raw_msgs = data.get("messages", [])
                sync_cursor = data.get("syncState") or sync_cursor

                early_break = False
                for raw in raw_msgs:
                    mid = str(raw.get("id") or "")
                    arrival = raw.get("originalarrivaltime") or ""

                    # Early-break check: stop if we hit existing messages in DB
                    if latest_mid and mid == str(latest_mid):
                        early_break = True
                        break
                    if latest_time and arrival and arrival <= latest_time:
                        early_break = True
                        break

                    norm = normalize_api_message(raw, self_id, chat_id)
                    if norm:
                        norm["reviewed"] = 0  # New incoming messages require review
                        norm["alerted"] = 0
                        if insert_message(conn, norm):
                            new_messages_count += 1

                if early_break:
                    break

                next_url = data.get("backwardLink")
                if not next_url:
                    break
            except Exception as e:
                err_msg = str(e)
                if "AUTH_EXPIRED" in err_msg:
                    print("Notice: Auth expired during sync, attempting token refresh...", file=sys.stderr)
                    try:
                        auth = harvest_teams_auth(tab_id, bridge_url=bridge_url, force_refresh=True)
                        continue
                    except Exception:
                        print("Error: Could not refresh Teams token. Please refresh Teams tab in Chrome.", file=sys.stderr)
                        return 1
                print(f"Notice: Chat '{title}' page {page+1} error ({e}).", file=sys.stderr)
                break

        upsert_chat(
            conn,
            chat_id=chat_id,
            title=title,
            chat_type=chat_type,
            last_scanned_at=datetime.now(timezone.utc).isoformat(),
            sync_cursor=sync_cursor,
        )

    print(f"Sync complete. Ingested {new_messages_count} new messages across {len(target_chats)} chat(s) ({total_requests_count} HTTP requests).")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Microsoft Teams Message Suite & Database CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # migrate
    p_mig = subparsers.add_parser("migrate", help="Migrate legacy JSON database into SQLite")
    p_mig.add_argument("--source", default=str(Path(__file__).parent / "msteam-database.json"), help="Source JSON path")
    p_mig.add_argument("--db", default=None, help="Target SQLite DB path")
    p_mig.set_defaults(func=cmd_migrate)

    # chats
    p_chats = subparsers.add_parser("chats", help="List all chats and their message statistics")
    p_chats.add_argument("--db", default=None, help="Database path")
    p_chats.set_defaults(func=cmd_chats)

    # log
    p_log = subparsers.add_parser("log", help="Inspect raw chat logs")
    p_log.add_argument("--chat", help="Filter by chat ID or title substring")
    p_log.add_argument("--author", help="Filter by author substring")
    p_log.add_argument("--search", help="Filter by text substring")
    p_log.add_argument("--limit", type=int, default=30, help="Maximum messages to display")
    p_log.add_argument("--offset", type=int, default=0, help="Pagination offset")
    p_log.add_argument("--db", default=None, help="Database path")
    p_log.set_defaults(func=cmd_log)

    # search
    p_srch = subparsers.add_parser("search", help="Full-text search using SQLite FTS5")
    p_srch.add_argument("query", help="Search query string")
    p_srch.add_argument("--limit", type=int, default=30, help="Result limit")
    p_srch.add_argument("--db", default=None, help="Database path")
    p_srch.set_defaults(func=cmd_search)

    # pending
    p_pend = subparsers.add_parser("pending", help="List messages pending review and summary")
    p_pend.add_argument("--chat", help="Filter by chat ID")
    p_pend.add_argument("--db", default=None, help="Database path")
    p_pend.set_defaults(func=cmd_pending)

    # ack
    p_ack = subparsers.add_parser("ack", help="Mark messages as reviewed")
    p_ack.add_argument("--ids", nargs="*", default=[], help="Message IDs to acknowledge")
    p_ack.add_argument("--all", action="store_true", help="Acknowledge all pending messages")
    p_ack.add_argument("--db", default=None, help="Database path")
    p_ack.set_defaults(func=cmd_ack)

    # export
    p_exp = subparsers.add_parser("export", help="Export messages to Markdown or JSON")
    p_exp.add_argument("--chat", help="Filter by chat ID or title substring")
    p_exp.add_argument("--format", choices=["md", "json"], default="md", help="Export format")
    p_exp.add_argument("--limit", type=int, default=1000, help="Maximum messages")
    p_exp.add_argument("--output", help="Output file path (prints to stdout if omitted)")
    p_exp.add_argument("--db", default=None, help="Database path")
    p_exp.set_defaults(func=cmd_export)

    # sync
    p_sync = subparsers.add_parser("sync", help="Synchronize messages from Teams tab via browser bridge")
    p_sync.add_argument("--chat", help="Filter sync to specific chat ID or title substring")
    p_sync.add_argument("--limit-chats", type=int, default=None, help="Limit number of chats to sync")
    p_sync.add_argument("--max-pages", type=int, default=1, help="Max pagination pages per chat (default: 1, 50 msgs/page)")
    p_sync.add_argument("--bridge-url", default=None, help="Browser bridge URL")
    p_sync.add_argument("--db", default=None, help="Database path")
    p_sync.set_defaults(func=cmd_sync)

    parsed = parser.parse_args(argv)
    return parsed.func(parsed)


if __name__ == "__main__":
    sys.exit(main())
