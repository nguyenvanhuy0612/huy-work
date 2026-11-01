"""Unit tests for Outlook and Gmail adapters."""

import unittest
from unittest.mock import MagicMock, patch

from skills.mail.adapters.gmail import (
    compose_gmail_email,
    find_gmail_tab,
    parse_thread_id_from_jslog,
    read_open_gmail_thread,
)
from skills.mail.adapters.outlook import compose_outlook_email, find_outlook_tab


class TestGmailAdapter(unittest.TestCase):
    def test_parse_thread_id_from_jslog(self) -> None:
        # Base64 for ["#thread-f:1880162029010259640"]
        packet = "1:WyIjdGhyZWFkLWY6MTg4MDE2MjAyOTAxMDI1OTY0MCJd"
        jslog = f"18406; u014N:xr6bB; {packet}"
        tid = parse_thread_id_from_jslog(jslog)
        self.assertEqual(tid, "1880162029010259640")

    def test_parse_thread_id_invalid(self) -> None:
        self.assertIsNone(parse_thread_id_from_jslog(""))
        self.assertIsNone(parse_thread_id_from_jslog("invalid;log;format"))

    @patch("skills.mail.adapters.gmail.list_tabs")
    @patch("skills.mail.adapters.gmail.get_tab_account")
    def test_find_gmail_tab_multi_account_match(self, mock_get_acc, mock_list_tabs) -> None:
        mock_list_tabs.return_value = [
            {"id": 10, "url": "https://mail.google.com/mail/u/0/", "title": "Work Mail"},
            {"id": 20, "url": "https://mail.google.com/mail/u/1/", "title": "Personal Mail"},
        ]
        # Tab 10 is work@corp.com, Tab 20 is personal@gmail.com
        mock_get_acc.side_effect = lambda tid, bridge_url: "work@corp.com" if tid == 10 else "personal@gmail.com"

        # Search for personal@gmail.com
        matched = find_gmail_tab(account="personal@gmail.com")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["id"], 20)

    @patch("skills.mail.adapters.gmail.eval_js")
    def test_compose_gmail_email(self, mock_eval_js) -> None:
        mock_eval_js.return_value = {"ok": True, "action": "draft_created"}
        res = compose_gmail_email(10, to="lead@test.com", subject="Subj", body="Body", cc="cc@test.com")
        self.assertTrue(res["ok"])
        self.assertEqual(res["action"], "draft_created")

    @patch("skills.mail.adapters.gmail.eval_js")
    def test_read_open_gmail_thread(self, mock_eval_js) -> None:
        mock_eval_js.return_value = {
            "subject": "Interview Process",
            "messages": [{"sender": "hr@test.com", "date": "10:00", "body": "Welcome"}],
        }
        res = read_open_gmail_thread(10)
        self.assertEqual(res["subject"], "Interview Process")
        self.assertEqual(len(res["messages"]), 1)


class TestOutlookAdapter(unittest.TestCase):
    @patch("skills.mail.adapters.outlook.find_tab")
    def test_find_outlook_tab(self, mock_find_tab) -> None:
        mock_find_tab.return_value = {"id": 55, "title": "Outlook"}
        tab = find_outlook_tab()
        self.assertIsNotNone(tab)
        self.assertEqual(tab["id"], 55)

    @patch("skills.mail.adapters.outlook.eval_js")
    def test_compose_outlook_email(self, mock_eval_js) -> None:
        mock_eval_js.return_value = {"ok": True, "action": "sent"}
        res = compose_outlook_email(55, to="corp@test.com", subject="Sync", body="Meeting link", send_now=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["action"], "sent")


if __name__ == "__main__":
    unittest.main()

