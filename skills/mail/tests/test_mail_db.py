"""Unit tests for mail_db."""

import tempfile
import unittest
from pathlib import Path

from skills.common.storage import get_db_connection
from skills.mail.mail_db import (
    acknowledge_emails,
    get_email_by_id,
    get_emails,
    get_pending_emails,
    init_db,
    search_fts,
    upsert_email,
)


class TestMailDatabase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_mail.db"
        self.conn = get_db_connection(self.db_path)
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_upsert_and_get_emails(self) -> None:
        is_new = upsert_email(
            self.conn,
            app="outlook",
            account="corp_user",
            email_id="out_1",
            conversation_id="conv_1",
            sender="Manager <manager@corp.com>",
            subject="Sprint Planning",
            snippet="Meeting starts at 10 AM",
            body="Full body of sprint planning meeting",
            timestamp="2026-10-31",
            is_read=False,
        )
        self.assertTrue(is_new)

        upsert_email(
            self.conn,
            app="gmail",
            account="nguyenvanhuy0612@gmail.com",
            email_id="gm_1",
            conversation_id="t100",
            sender="Recruiter <hr@company.com>",
            subject="Interview Offer",
            snippet="Congratulations on passing the QA assessment",
            body="We are pleased to extend an interview offer.",
            timestamp="2026-10-31",
            is_read=True,
        )

        all_emails = get_emails(self.conn)
        self.assertEqual(len(all_emails), 2)

        gmail_only = get_emails(self.conn, app="gmail", account="nguyenvanhuy0612@gmail.com")
        self.assertEqual(len(gmail_only), 1)
        self.assertEqual(gmail_only[0]["subject"], "Interview Offer")

    def test_fts_search_across_accounts(self) -> None:
        upsert_email(
            self.conn,
            app="gmail",
            account="user@gmail.com",
            email_id="e1",
            conversation_id="c1",
            sender="AWS Billing",
            subject="Monthly Invoice",
            snippet="Your invoice for October is ready",
        )
        results = search_fts(self.conn, "Invoice")
        self.assertEqual(len(results), 1)
        self.assertIn("<b>invoice</b>", results[0]["matched_snippet"].lower())

        # Search by sender
        results_sender = search_fts(self.conn, "Billing")
        self.assertEqual(len(results_sender), 1)
        self.assertIn("<b>billing</b>", results_sender[0]["matched_snippet"].lower())

    def test_pending_and_ack(self) -> None:
        upsert_email(
            self.conn,
            app="outlook",
            account="work",
            email_id="e_work",
            conversation_id="cw",
            sender="Alice",
            subject="Urgent review needed",
        )
        pending = get_pending_emails(self.conn)
        self.assertEqual(len(pending), 1)

        ack_count = acknowledge_emails(self.conn, app="outlook", all_pending=True)
        self.assertEqual(ack_count, 1)

        pending_after = get_pending_emails(self.conn)
        self.assertEqual(len(pending_after), 0)


if __name__ == "__main__":
    unittest.main()
