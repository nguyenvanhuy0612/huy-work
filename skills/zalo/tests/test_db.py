"""Unit tests for zalo.db."""

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
    format_zalo_timestamp,
    get_chat_latest_message_info,
    get_chats,
    get_db_connection,
    get_messages,
    get_pending_messages,
    init_db,
    insert_message,
    insert_messages_batch,
    search_fts,
    upsert_chat,
)


class TestZaloDatabase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_zalo.db"
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

    def test_classify_chat_type(self) -> None:
        self.assertEqual(classify_chat_type("0"), "cloud")
        self.assertEqual(classify_chat_type("cloud"), "cloud")
        self.assertEqual(classify_chat_type("div_TabMsg_ThrdChFileXFER"), "cloud")
        self.assertEqual(classify_chat_type("g1191331066876269725"), "group")
        self.assertEqual(classify_chat_type("some_id", is_group=True), "group")
        self.assertEqual(classify_chat_type("oa_123456", is_oa=True), "oa")
        self.assertEqual(classify_chat_type("1488132322898755251"), "direct")

    def test_format_zalo_timestamp(self) -> None:
        # Milliseconds epoch
        ts_ms = 1792987239688
        iso = format_zalo_timestamp(ts_ms)
        self.assertTrue(iso.endswith("Z"))
        self.assertIn("T", iso)

        # Seconds epoch
        ts_s = 1757251678
        iso_s = format_zalo_timestamp(ts_s)
        self.assertTrue(iso_s.endswith("Z"))
        self.assertIn("T", iso_s)

        # Already formatted ISO
        self.assertEqual(format_zalo_timestamp("2026-10-26T11:00:00.000Z"), "2026-10-26T11:00:00.000Z")
        self.assertEqual(format_zalo_timestamp(""), "")

    def test_upsert_chat_idempotency_and_metadata(self) -> None:
        upsert_chat(
            self.conn,
            chat_id="g1191331066876269725",
            title="secureAge",
            chat_type="group",
            last_activity="1792987239688",
            members=["Phước Hoàng", "Tiến Phan", "Nguyễn Văn Huy"],
            avatar="https://avatar.url/grp.jpg",
        )
        chats = get_chats(self.conn)
        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0]["title"], "secureAge")
        self.assertEqual(chats[0]["type"], "group")
        self.assertEqual(json.loads(chats[0]["members"]), ["Nguyễn Văn Huy", "Phước Hoàng", "Tiến Phan"])

        # Update title and activity
        upsert_chat(
            self.conn,
            chat_id="g1191331066876269725",
            title="secureAge Renamed",
            chat_type="group",
            last_activity="1792999999999",
        )
        chats = get_chats(self.conn)
        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0]["title"], "secureAge Renamed")

    def test_insert_message_and_latest_info(self) -> None:
        upsert_chat(self.conn, "7792528564668089393", "Út Yêu <3", "direct")

        # Initially no messages
        latest_time, latest_msg_id = get_chat_latest_message_info(self.conn, "7792528564668089393")
        self.assertIsNone(latest_time)
        self.assertIsNone(latest_msg_id)

        # Insert message
        msg1 = {
            "msg_id": "8416508367172",
            "cli_msg_id": "1792987239631",
            "chat_id": "7792528564668089393",
            "author": "Nguyễn Văn Huy",
            "from_uid": "0",
            "to_uid": "7792528564668089393",
            "text": "Ok nè",
            "time": "1792987239688",
            "is_mine": True,
        }
        self.assertTrue(insert_message(self.conn, msg1))

        # Duplicate insert returns False
        self.assertFalse(insert_message(self.conn, msg1))

        latest_time, latest_msg_id = get_chat_latest_message_info(self.conn, "7792528564668089393")
        self.assertEqual(latest_msg_id, "8416508367172")
        self.assertIsNotNone(latest_time)

    def test_insert_messages_batch_and_pending_flow(self) -> None:
        upsert_chat(self.conn, "c1", "Chat 1", "direct")
        messages = [
            {"msg_id": "m1", "chat_id": "c1", "author": "Alice", "text": "Hello", "time": "1000"},
            {"msg_id": "m2", "chat_id": "c1", "author": "Bob", "text": "Hi", "time": "2000"},
        ]
        inserted = insert_messages_batch(self.conn, messages)
        self.assertEqual(inserted, 2)

        pending = get_pending_messages(self.conn, "c1")
        self.assertEqual(len(pending), 2)

        # Acknowledge first message
        ack_count = acknowledge_messages(self.conn, [pending[0]["id"]])
        self.assertEqual(ack_count, 1)

        pending_after = get_pending_messages(self.conn, "c1")
        self.assertEqual(len(pending_after), 1)
        self.assertEqual(pending_after[0]["msg_id"], "m2")

    def test_search_fts(self) -> None:
        upsert_chat(self.conn, "c1", "QA Team", "group")
        insert_message(self.conn, {
            "msg_id": "m100",
            "chat_id": "c1",
            "author": "Johnny",
            "text": "Vị trí Automation QA Engineer đang open tuyển dụng",
            "time": "1000",
        })
        insert_message(self.conn, {
            "msg_id": "m101",
            "chat_id": "c1",
            "author": "Alice",
            "text": "Báo cáo test regression đã hoàn thành",
            "time": "2000",
        })

        results = search_fts(self.conn, "Automation QA")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["msg_id"], "m100")

        results2 = search_fts(self.conn, "regression")
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0]["msg_id"], "m101")


if __name__ == "__main__":
    unittest.main()
