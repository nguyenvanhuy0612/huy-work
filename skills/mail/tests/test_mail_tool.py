"""Unit tests for mail_tool CLI."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from skills.common.storage import get_db_connection
from skills.mail.mail_db import init_db, upsert_email
from skills.mail.mail_tool import main


class TestMailToolCLI(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_mail.db"
        conn = get_db_connection(self.db_path)
        init_db(conn)
        upsert_email(
            conn,
            app="gmail",
            account="user@gmail.com",
            email_id="gm1",
            conversation_id="conv_gm1",
            sender="Google Cloud <billing@google.com>",
            subject="Monthly Cloud Invoice",
            snippet="Your invoice is available for download",
            body="Full invoice details for your project.",
            timestamp="2026-10-31",
            is_read=False,
        )
        conn.close()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_list_emails(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = main(["--db", str(self.db_path), "list"])
        self.assertEqual(exit_code, 0)
        output = buf.getvalue()
        self.assertIn("GMAIL", output)
        self.assertIn("Monthly Cloud Invoice", output)

    def test_read_email(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = main(["--db", str(self.db_path), "read", "--id", "gm1"])
        self.assertEqual(exit_code, 0)
        output = buf.getvalue()
        self.assertIn("Full invoice details for your project.", output)

    def test_search_email(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = main(["--db", str(self.db_path), "search", "invoice"])
        self.assertEqual(exit_code, 0)
        output = buf.getvalue()
        self.assertIn("Monthly Cloud Invoice", output)

    def test_send_dry_run_blocks_outbound(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            # No --confirm flag passed
            exit_code = main([
                "--db", str(self.db_path),
                "--app", "gmail",
                "send",
                "--to", "lead@company.com",
                "--subject", "Status Report",
                "--body", "Weekly QA automated test execution complete.",
            ])
        self.assertEqual(exit_code, 0)
        output = buf.getvalue()
        self.assertIn("[OUTBOUND ACTION PREVIEW - APPROVAL REQUIRED]", output)
        self.assertIn("DRY RUN", output)
        self.assertIn("Weekly QA automated test execution complete.", output)

    @patch("skills.mail.mail_tool.find_gmail_tab")
    @patch("skills.mail.mail_tool.compose_gmail_email")
    def test_send_confirmed_executes(self, mock_compose, mock_find_tab) -> None:
        mock_find_tab.return_value = {"id": 10}
        mock_compose.return_value = {"ok": True, "action": "sent"}

        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = main([
                "--db", str(self.db_path),
                "--app", "gmail",
                "send",
                "--to", "lead@company.com",
                "--subject", "Status Report",
                "--body", "Execution complete.",
                "--confirm",
            ])
        self.assertEqual(exit_code, 0)
        output = buf.getvalue()
        self.assertIn("Successfully sent email via Gmail", output)
        mock_compose.assert_called_once()

    @patch("skills.mail.mail_tool.find_gmail_tab")
    @patch("skills.mail.mail_tool.compose_gmail_email")
    def test_draft_executes(self, mock_compose, mock_find_tab) -> None:
        mock_find_tab.return_value = {"id": 10}
        mock_compose.return_value = {"ok": True, "action": "draft_created"}

        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = main([
                "--db", str(self.db_path),
                "--app", "gmail",
                "draft",
                "--to", "lead@company.com",
                "--subject", "Status Report",
                "--body", "Execution complete.",
            ])
        self.assertEqual(exit_code, 0)
        output = buf.getvalue()
        self.assertIn("Draft created successfully in Gmail compose pane", output)
        mock_compose.assert_called_once()


if __name__ == "__main__":
    unittest.main()

