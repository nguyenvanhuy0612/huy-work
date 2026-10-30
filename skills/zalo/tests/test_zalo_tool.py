"""Unit tests for zalo.zalo_tool."""

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add scripts directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from db import (
    get_db_connection,
    init_db,
    insert_message,
    upsert_chat,
)
from zalo_tool import main


class TestZaloTool(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_cli.db"
        self.conn = get_db_connection(self.db_path)
        init_db(self.conn)

        upsert_chat(
            self.conn,
            chat_id="g100",
            title="Automation Team",
            chat_type="group",
            last_activity="2026-10-26T10:00:00.000Z",
            members=["Huy", "Alice"],
        )
        insert_message(self.conn, {
            "msg_id": "m1",
            "chat_id": "g100",
            "author": "Alice",
            "text": "Daily standup at 10 AM",
            "time": "2026-10-26T10:00:00.000Z",
            "reviewed": 0,
        })
        self.conn.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_cmd_chats(self) -> None:
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            code = main(["chats", "--db", str(self.db_path)])
            self.assertEqual(code, 0)
            output = fake_out.getvalue()
            self.assertIn("Automation Team", output)
            self.assertIn("group", output)

    def test_cmd_log(self) -> None:
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            code = main(["log", "--chat", "g100", "--db", str(self.db_path)])
            self.assertEqual(code, 0)
            output = fake_out.getvalue()
            self.assertIn("Daily standup", output)
            self.assertIn("Alice", output)

    def test_cmd_search(self) -> None:
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            code = main(["search", "standup", "--db", str(self.db_path)])
            self.assertEqual(code, 0)
            output = fake_out.getvalue()
            self.assertIn("standup", output)
            self.assertIn("Alice", output)

    def test_cmd_pending_and_ack(self) -> None:
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            code = main(["pending", "--db", str(self.db_path)])
            self.assertEqual(code, 0)
            self.assertIn("Daily standup", fake_out.getvalue())

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            code = main(["ack", "--all", "--db", str(self.db_path)])
            self.assertEqual(code, 0)
            self.assertIn("Acknowledged 1 messages", fake_out.getvalue())

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            code = main(["pending", "--db", str(self.db_path)])
            self.assertEqual(code, 0)
            self.assertIn("No pending messages", fake_out.getvalue())

    def test_cmd_export(self) -> None:
        export_file = Path(self.temp_dir.name) / "export.md"
        code = main(["export", "--chat", "g100", "--output", str(export_file), "--db", str(self.db_path)])
        self.assertEqual(code, 0)
        self.assertTrue(export_file.exists())
        content = export_file.read_text(encoding="utf-8")
        self.assertIn("Daily standup", content)

    def test_cmd_digest(self) -> None:
        digest_file = Path(self.temp_dir.name) / "SUMMARY.md"
        code = main(["digest", "--output", str(digest_file), "--db", str(self.db_path)])
        self.assertEqual(code, 0)
        self.assertTrue(digest_file.exists())
        content = digest_file.read_text(encoding="utf-8")
        self.assertIn("Executive Dashboard", content)
        self.assertIn("Automation Team", content)

    @patch("zalo_tool.find_zalo_tab")
    @patch("zalo_tool.harvest_conversations")
    def test_cmd_sync(self, mock_harvest: MagicMock, mock_find: MagicMock) -> None:
        mock_find.return_value = {"id": 12345, "title": "Zalo - Test"}
        mock_harvest.return_value = (
            {"userId": "u1", "displayName": "Tester"},
            [
                {
                    "chat_id": "c99",
                    "title": "Synced Chat",
                    "category": "direct",
                    "last_activity": "2026-10-26T11:00:00.000Z",
                    "unread_count": 0,
                    "members": [],
                    "avatar": "",
                    "last_message": {
                        "msg_id": "m99",
                        "text": "Hello sync",
                        "time": "2026-10-26T11:00:00.000Z",
                    },
                }
            ],
        )
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            code = main(["sync", "--db", str(self.db_path)])
            self.assertEqual(code, 0)
            output = fake_out.getvalue()
            self.assertIn("Sync complete", output)


if __name__ == "__main__":
    unittest.main()
