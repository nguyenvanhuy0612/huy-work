"""Unit tests for chat_tool CLI."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from skills.chat.chat_db import init_db, insert_message, upsert_chat
from skills.chat.chat_tool import main
from skills.common.storage import get_db_connection


class TestChatToolCLI(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_chat.db"
        conn = get_db_connection(self.db_path)
        init_db(conn)
        upsert_chat(conn, "teams", "t1", "Release Channel", category="channel")
        msg = {
            "mid": "m1",
            "chat_id": "t1",
            "author": "Alice",
            "time": "2026-10-31T09:00:00Z",
            "text": "Production deploy started.",
        }
        insert_message(conn, "teams", msg)
        conn.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_list_chats(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = main(["--db", str(self.db_path), "list"])
        self.assertEqual(exit_code, 0)
        output = buf.getvalue()
        self.assertIn("TEAMS", output)
        self.assertIn("Release Channel", output)

    def test_log_chat(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = main(["--db", str(self.db_path), "--app", "teams", "log", "--chat", "Release Channel"])
        self.assertEqual(exit_code, 0)
        output = buf.getvalue()
        self.assertIn("Production deploy started.", output)

    def test_search(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = main(["--db", str(self.db_path), "search", "deploy"])
        self.assertEqual(exit_code, 0)
        output = buf.getvalue()
        self.assertIn("Production <b>deploy</b> started.", output)

    def test_send_dry_run_blocks_outbound(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            # No --confirm flag passed
            exit_code = main(["--db", str(self.db_path), "--app", "teams", "send", "--chat", "t1", "--message", "Hi team"])
        self.assertEqual(exit_code, 0)
        output = buf.getvalue()
        self.assertIn("[OUTBOUND ACTION PREVIEW - APPROVAL REQUIRED]", output)
        self.assertIn("DRY RUN", output)

    @patch("skills.chat.chat_tool.send_teams_message_direct")
    @patch("skills.chat.chat_tool.find_teams_tab")
    @patch("skills.chat.chat_tool.harvest_teams_auth")
    def test_send_confirmed_executes(self, mock_auth, mock_tab, mock_send) -> None:
        mock_tab.return_value = {"id": 1}
        mock_auth.return_value = {"token": "tok", "region": "apac"}
        mock_send.return_value = {"ok": True}

        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = main(["--db", str(self.db_path), "--app", "teams", "send", "--chat", "t1", "--message", "Hi team", "--confirm"])
        self.assertEqual(exit_code, 0)
        output = buf.getvalue()
        self.assertIn("Successfully sent message to Teams chat", output)
        mock_send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
