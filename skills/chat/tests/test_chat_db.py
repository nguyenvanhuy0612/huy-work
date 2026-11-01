"""Unit tests for chat_db."""

import tempfile
import unittest
from pathlib import Path

from skills.chat.chat_db import (
    acknowledge_messages,
    classify_chat_type,
    export_markdown,
    get_chats,
    get_messages,
    get_pending_messages,
    init_db,
    insert_message,
    insert_messages_batch,
    search_fts,
    upsert_chat,
)
from skills.common.storage import get_db_connection


class TestChatDatabase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_chat.db"
        self.conn = get_db_connection(self.db_path)
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_classify_chat_type(self) -> None:
        self.assertEqual(classify_chat_type("48:notes"), "personal")
        self.assertEqual(classify_chat_type("19:user1_user2@unq.gbl.spaces"), "direct")
        self.assertEqual(classify_chat_type("19:general@thread.tacv2"), "channel")
        self.assertEqual(classify_chat_type("g123456"), "group")
        self.assertEqual(classify_chat_type("19:group@thread.v2"), "group")
        self.assertEqual(classify_chat_type("cloud"), "cloud")

    def test_upsert_and_get_chats(self) -> None:
        upsert_chat(self.conn, "teams", "t1", "Engineering Team", category="channel")
        upsert_chat(self.conn, "zalo", "z1", "Family Group", category="group")

        all_chats = get_chats(self.conn)
        self.assertEqual(len(all_chats), 2)

        teams_chats = get_chats(self.conn, app="teams")
        self.assertEqual(len(teams_chats), 1)
        self.assertEqual(teams_chats[0]["title"], "Engineering Team")

    def test_insert_messages_and_fts_search(self) -> None:
        upsert_chat(self.conn, "teams", "t1", "Engineering Team")
        msg = {
            "mid": "m100",
            "chat_id": "t1",
            "author": "Alice",
            "is_mine": False,
            "time": "2026-10-30T10:00:00Z",
            "text": "The deployment pipeline has succeeded with zero errors.",
        }
        inserted = insert_message(self.conn, "teams", msg)
        self.assertTrue(inserted)

        # FTS Search across all or by app
        results = search_fts(self.conn, "pipeline")
        self.assertEqual(len(results), 1)
        self.assertIn("<b>pipeline</b>", results[0]["matched_snippet"])

        # Search by author
        results_author = search_fts(self.conn, "Alice")
        self.assertEqual(len(results_author), 1)
        self.assertIn("<b>alice</b>", results_author[0]["matched_snippet"].lower())

        # Pending check & acknowledge
        pending = get_pending_messages(self.conn)
        self.assertEqual(len(pending), 1)

        ack_count = acknowledge_messages(self.conn, app="teams", all_pending=True)
        self.assertEqual(ack_count, 1)

        pending_after = get_pending_messages(self.conn)
        self.assertEqual(len(pending_after), 0)

    def test_export_markdown(self) -> None:
        upsert_chat(self.conn, "zalo", "z1", "QA Sync")
        msg = {
            "mid": "z_m1",
            "chat_id": "z1",
            "author": "Bob",
            "is_mine": False,
            "time": "2026-10-30T10:05:00Z",
            "text": "All test cases passed.",
        }
        insert_message(self.conn, "zalo", msg)
        out_file = Path(self.temp_dir.name) / "qa_export.md"
        count = export_markdown(self.conn, "zalo", "z1", out_file)
        self.assertEqual(count, 1)
        content = out_file.read_text(encoding="utf-8")
        self.assertIn("# Chat Export: QA Sync", content)
        self.assertIn("All test cases passed.", content)


if __name__ == "__main__":
    unittest.main()

