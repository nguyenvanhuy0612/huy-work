"""Unit tests for msteam.db."""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# Add scripts directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from db import (
    acknowledge_messages,
    classify_chat_type,
    get_chat_latest_message_info,
    get_chat_sync_cursor,
    get_chats,
    get_db_connection,
    get_messages,
    get_pending_messages,
    init_db,
    insert_message,
    insert_messages_batch,
    migrate_from_json,
    search_fts,
    upsert_chat,
)


class TestDatabase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_teams.db"
        self.conn = get_db_connection(self.db_path)
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_init_db_creates_tables_and_indices(self) -> None:
        cursor = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        self.assertIn("chats", tables)
        self.assertIn("messages", tables)
        self.assertIn("messages_fts", tables)

    def test_classify_chat_type_prefixes(self) -> None:
        self.assertEqual(classify_chat_type("48:notes"), "personal")
        self.assertEqual(classify_chat_type("48:personal_board"), "personal")
        self.assertEqual(classify_chat_type("19:user1_user2@unq.gbl.spaces"), "direct")
        self.assertEqual(classify_chat_type("19:general@thread.tacv2"), "channel")
        self.assertEqual(classify_chat_type("19:group123@thread.v2"), "group")
        self.assertEqual(classify_chat_type("custom_external_id"), "group")

    def test_upsert_chat_idempotency_and_metadata(self) -> None:
        upsert_chat(self.conn, "chat1", "Project Team", "group", "2026-10-21 10:00:00", members=["Alice", "Bob"])
        chats = get_chats(self.conn)
        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0]["title"], "Project Team")
        self.assertEqual(json.loads(chats[0]["members"]), ["Alice", "Bob"])

        # Update title and members
        upsert_chat(self.conn, "chat1", "Project Team Renamed", "group", "2026-10-21 11:00:00", members=["Charlie"])
        chats = get_chats(self.conn)
        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0]["title"], "Project Team Renamed")
        self.assertEqual(chats[0]["last_activity"], "2026-10-21 11:00:00")

    def test_sync_cursor_and_latest_message_info(self) -> None:
        upsert_chat(
            self.conn,
            "19:test@thread.v2",
            "Delta Test Group",
            sync_cursor="https://teams.cloud.microsoft/cursor_v1",
        )
        chat = get_chats(self.conn)[0]
        self.assertEqual(chat["type"], "group")
        self.assertEqual(chat["sync_cursor"], "https://teams.cloud.microsoft/cursor_v1")
        self.assertEqual(get_chat_sync_cursor(self.conn, "19:test@thread.v2"), "https://teams.cloud.microsoft/cursor_v1")

        # Initially no messages
        latest_time, latest_mid = get_chat_latest_message_info(self.conn, "19:test@thread.v2")
        self.assertIsNone(latest_time)
        self.assertIsNone(latest_mid)

        # Insert messages with different timestamps
        insert_message(self.conn, {
            "mid": "mid_100",
            "chat_id": "19:test@thread.v2",
            "author": "Alice",
            "time": "2026-10-25T10:00:00.000Z",
            "text": "Message 1",
        })
        insert_message(self.conn, {
            "mid": "mid_200",
            "chat_id": "19:test@thread.v2",
            "author": "Bob",
            "time": "2026-10-25T11:00:00.000Z",
            "text": "Message 2",
        })

        latest_time, latest_mid = get_chat_latest_message_info(self.conn, "19:test@thread.v2")
        self.assertEqual(latest_time, "2026-10-25T11:00:00.000Z")
        self.assertEqual(latest_mid, "mid_200")

    def test_insert_and_pending_messages_workflow(self) -> None:
        upsert_chat(self.conn, "chat1", "General", "group")
        msg = {
            "mid": "1001",
            "chat_id": "chat1",
            "author": "Alice",
            "time": "2026-10-21 10:05:00",
            "text": "Please review release PR #42",
            "reviewed": 0,
        }
        inserted = insert_message(self.conn, msg)
        self.assertTrue(inserted)

        # Duplicate insert returns False
        inserted_dup = insert_message(self.conn, msg)
        self.assertFalse(inserted_dup)

        pending = get_pending_messages(self.conn)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["mid"], "1001")
        self.assertEqual(pending[0]["reviewed"], 0)

        # Acknowledge
        ack_count = acknowledge_messages(self.conn, [pending[0]["id"]])
        self.assertEqual(ack_count, 1)

        pending_after = get_pending_messages(self.conn)
        self.assertEqual(len(pending_after), 0)

    def test_fts5_search_ranking_and_snippet(self) -> None:
        upsert_chat(self.conn, "chat1", "QA Automation", "group")
        insert_message(self.conn, {
            "mid": "2001",
            "chat_id": "chat1",
            "author": "Huy",
            "time": "2026-10-21 10:10:00",
            "text": "Deployment blocker identified on test environment.",
        })
        insert_message(self.conn, {
            "mid": "2002",
            "chat_id": "chat1",
            "author": "Dat",
            "time": "2026-10-21 10:12:00",
            "text": "Everything looks smooth on production.",
        })

        results = search_fts(self.conn, "blocker")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["mid"], "2001")
        self.assertIn("<b>blocker</b>", results[0]["highlighted_snippet"])

    def test_migrate_from_legacy_json(self) -> None:
        sample_json_path = Path(self.temp_dir.name) / "sample_teams.json"
        sample_data = {
            "version": "2.0",
            "groups": {
                "Project Alpha": {
                    "chatId": "thread.alpha",
                    "type": "group",
                    "lastActivity": "2026-10-20 12:00:00",
                    "members": ["Member1", "Member2"],
                    "messages": [
                        {"id": "msg1", "time": "2026-10-20 11:00:00", "author": "Member1", "text": "Hello Alpha"},
                        {"id": "msg2", "time": "2026-10-20 12:00:00", "author": "Member2", "text": "Agreed on plan"},
                    ]
                }
            }
        }
        sample_json_path.write_text(json.dumps(sample_data), encoding="utf-8")

        chats_c, msgs_c = migrate_from_json(sample_json_path, self.db_path)
        self.assertEqual(chats_c, 1)
        self.assertEqual(msgs_c, 2)

        messages = get_messages(self.conn, chat_id="thread.alpha")
        self.assertEqual(len(messages), 2)
        self.assertEqual(len(get_pending_messages(self.conn)), 0)


if __name__ == "__main__":
    unittest.main()
