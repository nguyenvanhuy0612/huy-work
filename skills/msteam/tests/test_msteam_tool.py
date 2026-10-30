"""Unit tests for msteam.msteam_tool."""

import sys
import tempfile
import unittest
from pathlib import Path

# Add scripts directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from db import get_db_connection, init_db, insert_message, upsert_chat
from msteam_tool import main


class TestMSteamToolCLI(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_cli.db"
        conn = get_db_connection(self.db_path)
        init_db(conn)
        upsert_chat(conn, "chat1", "Test Chat", "direct")
        insert_message(conn, {
            "mid": "mid_1",
            "chat_id": "chat1",
            "author": "Alice",
            "time": "2026-10-25T10:00:00.000Z",
            "text": "CLI test message text",
            "reviewed": 0,
        })
        conn.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_cli_chats_command(self) -> None:
        code = main(["chats", "--db", str(self.db_path)])
        self.assertEqual(code, 0)

    def test_cli_log_command(self) -> None:
        code = main(["log", "--chat", "chat1", "--db", str(self.db_path)])
        self.assertEqual(code, 0)

    def test_cli_search_command(self) -> None:
        code = main(["search", "CLI", "--db", str(self.db_path)])
        self.assertEqual(code, 0)

    def test_cli_pending_and_ack_command(self) -> None:
        code_pend = main(["pending", "--db", str(self.db_path)])
        self.assertEqual(code_pend, 0)

        code_ack = main(["ack", "--all", "--db", str(self.db_path)])
        self.assertEqual(code_ack, 0)

    def test_cli_export_markdown(self) -> None:
        out_file = Path(self.temp_dir.name) / "export.md"
        code = main(["export", "--chat", "chat1", "--output", str(out_file), "--db", str(self.db_path)])
        self.assertEqual(code, 0)
        self.assertTrue(out_file.exists())
        self.assertIn("CLI test message text", out_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
