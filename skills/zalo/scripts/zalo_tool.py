#!/usr/bin/env python3
"""Zalo CLI Tool for SQLite ingestion, querying, and summary workflows."""

import argparse
import datetime
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure script directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from bridge import (
        DEFAULT_BRIDGE_URL,
        find_zalo_tab,
        harvest_active_messages,
        harvest_conversations,
        select_conversation,
    )
    from db import (
        acknowledge_messages,
        classify_chat_type,
        format_zalo_timestamp,
        get_chat_latest_message_info,
        get_chats,
        get_db_connection,
        get_default_db_path,
        get_messages,
        get_pending_messages,
        init_db,
        insert_message,
        search_fts,
        upsert_chat,
    )
except ImportError:
    from .bridge import (
        DEFAULT_BRIDGE_URL,
        find_zalo_tab,
        harvest_active_messages,
        harvest_conversations,
        select_conversation,
    )
    from .db import (
        acknowledge_messages,
        classify_chat_type,
        format_zalo_timestamp,
        get_chat_latest_message_info,
        get_chats,
        get_db_connection,
        get_default_db_path,
        get_messages,
        get_pending_messages,
        init_db,
        insert_message,
        search_fts,
        upsert_chat,
    )


def cmd_chats(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    try:
        chats = get_chats(conn, category=args.category)
        if not chats:
            print("No chats found in database.")
            return 0

        print(f"{'TITLE':<38} | {'TYPE':<7} | {'UNREAD':<6} | {'LAST ACTIVITY':<24} | {'CHAT ID'}")
        print("-" * 105)
        for c in chats:
            title = c["title"][:36] + ".." if len(c["title"]) > 38 else c["title"]
            last_act = (c["last_activity"] or "N/A")[:24]
            print(f"{title:<38} | {c['type']:<7} | {c['unread_count']:<6} | {last_act:<24} | {c['chat_id']}")
        return 0
    finally:
        conn.close()


def cmd_log(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    try:
        target_chat_id = args.chat
        if target_chat_id:
            # Check if args.chat is a title substring
            all_chats = get_chats(conn)
            match = [c for c in all_chats if target_chat_id.lower() == c["chat_id"].lower() or target_chat_id.lower() in c["title"].lower()]
            if match:
                target_chat_id = match[0]["chat_id"]

        messages = get_messages(conn, chat_id=target_chat_id, limit=args.limit) if target_chat_id else []
        if not messages and not target_chat_id:
            # If no chat specified, collect recent messages from top chats
            all_chats = get_chats(conn)
            for c in all_chats[:5]:
                msgs = get_messages(conn, chat_id=c["chat_id"], limit=5)
                messages.extend(msgs)
            messages.sort(key=lambda m: m["time"])

        if not messages:
            print("No messages found matching criteria.")
            return 0

        for m in messages:
            author = m["author"]
            time_str = m["time"][:19] if len(m["time"]) >= 19 else m["time"]
            prefix = f"[{time_str}] {author}:"
            print(f"\033[1;36m{prefix}\033[0m")
            for line in (m["text"] or "").splitlines():
                print(f"  {line}")
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
            time_str = r["time"][:19] if len(r["time"]) >= 19 else r["time"]
            print(f"[{time_str}] {r['author']} in '{r['chat_title']}':")
            snippet = r["match_snippet"] or r["text"]
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
                time_str = m["time"][:19] if len(m["time"]) >= 19 else m["time"]
                print(f"  [{time_str}] {m['author']}: {m['text'][:120]}")
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
        chat_id = args.chat
        messages = get_messages(conn, chat_id=chat_id, limit=args.limit) if chat_id else []
        output_path = Path(args.output) if args.output else None

        if args.format == "json":
            data = [dict(m) for m in messages]
            rendered = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            lines = [f"# Zalo Export: {chat_id or 'All Chats'}\n"]
            for m in messages:
                lines.append(f"### [{m['time']}] {m['author']}")
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
        tab = find_zalo_tab(bridge_url)
    except Exception as err:
        print(f"Could not connect to browser bridge ({err}). Is Chrome running with the bridge?", file=sys.stderr)
        return 1

    if not tab:
        print("No active Zalo Web tab found in browser.", file=sys.stderr)
        return 1

    tab_id = tab["id"]
    print(f"Found Zalo tab: ID {tab_id} - '{tab.get('title')}'")

    try:
        user_info, convs = harvest_conversations(tab_id, bridge_url=bridge_url)
    except Exception as err:
        print(f"Error harvesting Zalo conversations: {err}", file=sys.stderr)
        return 1

    user_name = user_info.get("displayName", "Me") if user_info else "Me"
    user_id = user_info.get("userId", "") if user_info else ""
    print(f"Harvested {len(convs)} conversations from Zalo Web for user '{user_name}'.")

    target_convs = convs
    if getattr(args, "chat", None):
        needle = args.chat.lower()
        target_convs = [
            c for c in convs
            if needle == c.get("chat_id", "").lower() or needle in c.get("title", "").lower()
        ]
        print(f"Filtered to {len(target_convs)} target conversation(s) matching '{args.chat}'.")

    if getattr(args, "limit_chats", None) and args.limit_chats > 0:
        target_convs = target_convs[:args.limit_chats]

    new_messages_count = 0
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    for c in target_convs:
        cid = c.get("chat_id")
        title = c.get("title")
        if not cid or not title:
            continue

        upsert_chat(
            conn,
            chat_id=cid,
            title=title,
            chat_type=c.get("category"),
            last_activity=c.get("last_activity"),
            last_scanned_at=now_iso,
            unread_count=c.get("unread_count", 0),
            members=c.get("members", []),
            avatar=c.get("avatar", ""),
        )

        last_msg = c.get("last_message")
        if last_msg and (last_msg.get("msg_id") or last_msg.get("cli_msg_id")):
            if not last_msg.get("chat_id"):
                last_msg["chat_id"] = cid
            if insert_message(conn, last_msg):
                new_messages_count += 1

        # Deep sync: switch conversation and harvest active messages if requested
        if getattr(args, "deep", False):
            try:
                if select_conversation(tab_id, cid, bridge_url=bridge_url):
                    time.sleep(0.3)
                    deep_msgs = harvest_active_messages(
                        tab_id,
                        chat_id=cid,
                        current_user_name=user_name,
                        bridge_url=bridge_url,
                    )
                    for dm in deep_msgs:
                        if insert_message(conn, dm):
                            new_messages_count += 1
            except Exception as e:
                print(f"Notice: Deep sync for chat '{title}' encountered issue ({e}).", file=sys.stderr)

    print(f"Sync complete. Ingested {new_messages_count} new messages across {len(target_convs)} conversation(s).")
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    conn = get_db_connection(Path(args.db) if args.db else None)
    try:
        chats = get_chats(conn)
        if not chats:
            print("No chats found in database. Run sync first.")
            return 0

        output_path = Path(args.output) if args.output else Path(__file__).resolve().parent / "SUMMARY.md"
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        total_msgs = 0
        cursor = conn.execute("SELECT COUNT(*) FROM messages;")
        row = cursor.fetchone()
        if row:
            total_msgs = row[0]

        lines = [
            "# Zalo - Master Activity & Decision Digest",
            f"> Cập nhật lần cuối: {now_str} | Tổng số hội thoại: {len(chats)} | Tổng số tin nhắn: {total_msgs}\n",
            "---",
            "\n## 1. Executive Dashboard (Bảng điều hành các Hội thoại)\n",
            "| Kênh / Hội thoại | Loại | Tin nhắn gần nhất | Thời gian cập nhật | Trạng thái |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]

        for c in chats:
            cid = c["chat_id"]
            msgs = get_messages(conn, chat_id=cid, limit=1)
            last_msg_snippet = ""
            if msgs:
                txt = msgs[0]["text"].replace("\n", " ")
                last_msg_snippet = (txt[:50] + "..") if len(txt) > 50 else txt
            else:
                last_msg_snippet = "Chưa có tin nhắn lưu"

            ctype = c["type"].capitalize()
            last_act = (c["last_activity"] or "N/A")[:16].replace("T", " ")
            status = "Unread" if c["unread_count"] > 0 else "Active"
            lines.append(f"| **{c['title']}** | {ctype} | {last_msg_snippet} | {last_act} | {status} |")

        lines.extend([
            "\n---",
            "\n## 2. Chi tiết hoạt động các Hội thoại trọng điểm\n",
        ])

        # Top 10 chats with detailed breakdown
        for i, c in enumerate(chats[:10], start=1):
            cid = c["chat_id"]
            msgs = get_messages(conn, chat_id=cid, limit=5)
            members = json.loads(c["members"] or "[]")
            member_str = ", ".join(members) if members else "Trò chuyện 1-1"

            lines.append(f"### 2.{i}. {c['title']} ({c['type'].capitalize()})")
            lines.append(f"- **Thành viên / Đối tác:** {member_str}")
            lines.append(f"- **Cập nhật gần nhất:** {c['last_activity'] or 'N/A'}")
            lines.append("- **Các trao đổi gần đây:**")
            if msgs:
                for m in msgs:
                    time_short = m["time"][:16].replace("T", " ") if m["time"] else ""
                    lines.append(f"  - `[{time_short}]` **{m['author']}:** {m['text']}")
            else:
                lines.append("  - *(Chưa có dữ liệu chi tiết)*")
            lines.append("\n---\n")

        rendered = "\n".join(lines)
        output_path.write_text(rendered, encoding="utf-8")
        print(f"Generated digest to {output_path}")
        return 0
    finally:
        conn.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Zalo Message Suite & Database CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # chats
    p_chats = subparsers.add_parser("chats", help="List all chats and their message statistics")
    p_chats.add_argument("--category", choices=["direct", "group", "oa", "cloud"], help="Filter by category")
    p_chats.add_argument("--db", default=None, help="Database path")
    p_chats.set_defaults(func=cmd_chats)

    # log
    p_log = subparsers.add_parser("log", help="Inspect chat logs")
    p_log.add_argument("--chat", help="Filter by chat ID or title substring")
    p_log.add_argument("--limit", type=int, default=30, help="Maximum messages to display")
    p_log.add_argument("--db", default=None, help="Database path")
    p_log.set_defaults(func=cmd_log)

    # search
    p_srch = subparsers.add_parser("search", help="Full-text search using SQLite FTS5")
    p_srch.add_argument("query", help="Search query string")
    p_srch.add_argument("--limit", type=int, default=30, help="Result limit")
    p_srch.add_argument("--db", default=None, help="Database path")
    p_srch.set_defaults(func=cmd_search)

    # pending
    p_pend = subparsers.add_parser("pending", help="List messages pending review")
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
    p_sync = subparsers.add_parser("sync", help="Synchronize conversations & messages from Zalo tab")
    p_sync.add_argument("--chat", help="Filter sync to specific chat ID or title substring")
    p_sync.add_argument("--limit-chats", type=int, default=None, help="Limit number of chats to sync")
    p_sync.add_argument("--deep", action="store_true", help="Perform in-tab deep sync for active chat messages")
    p_sync.add_argument("--bridge-url", default=None, help="Browser bridge URL")
    p_sync.add_argument("--db", default=None, help="Database path")
    p_sync.set_defaults(func=cmd_sync)

    # digest
    p_dig = subparsers.add_parser("digest", help="Generate or update SUMMARY.md digest")
    p_dig.add_argument("--output", default=None, help="Output markdown path")
    p_dig.add_argument("--db", default=None, help="Database path")
    p_dig.set_defaults(func=cmd_digest)

    parsed = parser.parse_args(argv)
    return parsed.func(parsed)


if __name__ == "__main__":
    sys.exit(main())
