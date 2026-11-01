"""Unit tests for common communication infrastructure."""

import tempfile
import unittest
from pathlib import Path

from skills.common.safety import guard_outbound, render_preview
from skills.common.storage import clean_fts_query, get_db_connection


class TestCommonStorage(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_get_db_connection_pragmas(self) -> None:
        conn = get_db_connection(self.db_path)
        try:
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            self.assertEqual(mode.lower(), "wal")
            sync = conn.execute("PRAGMA synchronous;").fetchone()[0]
            # Normal is 1
            self.assertIn(sync, (1, "NORMAL", "normal"))
        finally:
            conn.close()

    def test_clean_fts_query(self) -> None:
        self.assertEqual(clean_fts_query(""), "")
        self.assertEqual(clean_fts_query("hello world"), '"hello"* AND "world"*')
        self.assertEqual(clean_fts_query("test!@#$%^&*()"), '"test"*')


class TestCommonSafety(unittest.TestCase):
    def test_render_preview(self) -> None:
        preview = render_preview(
            service="teams",
            action="Send Message",
            target="19:group123",
            body="Hello Team",
            subject="Release Notes",
        )
        self.assertIn("[OUTBOUND ACTION PREVIEW - APPROVAL REQUIRED]", preview)
        self.assertIn("Service : TEAMS", preview)
        self.assertIn("Target  : 19:group123", preview)
        self.assertIn("Subject : Release Notes", preview)
        self.assertIn("Hello Team", preview)

    def test_guard_outbound_dry_run_blocks(self) -> None:
        allowed = guard_outbound(
            confirmed=False,
            service="gmail",
            action="Send Email",
            target="lead@example.com",
            body="Draft email",
        )
        self.assertFalse(allowed)

    def test_guard_outbound_confirmed_passes(self) -> None:
        allowed = guard_outbound(
            confirmed=True,
            service="gmail",
            action="Send Email",
            target="lead@example.com",
            body="Draft email",
        )
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()

