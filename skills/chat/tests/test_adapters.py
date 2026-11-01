"""Unit tests for Teams and Zalo adapters."""

import time
import unittest
from unittest.mock import MagicMock, patch

from skills.chat.adapters.teams import (
    clear_auth_cache,
    decode_html_text,
    get_cached_auth,
    normalize_api_message,
    send_teams_message_direct,
)
import skills.chat.adapters.teams as teams_adapter
from skills.chat.adapters.zalo import normalize_zalo_message, send_zalo_message


class TestTeamsAdapter(unittest.TestCase):
    def test_decode_html_text(self) -> None:
        raw = "<p>Line 1<br/>Line 2 &amp; &lt;brackets&gt;</p>"
        self.assertEqual(decode_html_text(raw), "Line 1\nLine 2 & <brackets>")

    def test_normalize_api_message(self) -> None:
        raw = {
            "id": "12345",
            "messagetype": "RichText/Html",
            "originalarrivaltime": "2026-10-31T08:00:00Z",
            "from": "8:orgid:my-user-id",
            "imdisplayname": "Huy Nguyen",
            "content": "<div>Automated test run finished.</div>",
        }
        res = normalize_api_message(raw, self_id="my-user-id", chat_id="19:group1")
        self.assertIsNotNone(res)
        self.assertEqual(res["mid"], "12345")
        self.assertTrue(res["is_mine"])
        self.assertEqual(res["text"], "Automated test run finished.")

    def test_auth_cache_ttl(self) -> None:
        clear_auth_cache()
        self.assertIsNone(get_cached_auth())
        teams_adapter._AUTH_CACHE = {
            "token": "test_tok",
            "expiresOn": (time.time() + 3600) * 1000,
        }
        self.assertIsNotNone(get_cached_auth())

    @patch("urllib.request.urlopen")
    def test_send_teams_message_direct(self, mock_urlopen) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"id": "msg_sent_99"}'
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        auth = {"token": "token123", "region": "apac"}
        res = send_teams_message_direct(auth, "19:chat123", "Test message content")
        self.assertTrue(res["ok"])
        self.assertEqual(res["result"]["id"], "msg_sent_99")


class TestZaloAdapter(unittest.TestCase):
    def test_normalize_zalo_message(self) -> None:
        raw = {
            "msg_id": "zmsg_1",
            "chat_id": "g123",
            "author": "Alice",
            "text": "Hello from Zalo",
            "time": "1730000000",
        }
        res = normalize_zalo_message(raw, current_user_id="user_me", chat_id="g123")
        self.assertIsNotNone(res)
        self.assertEqual(res["mid"], "zmsg_1")
        self.assertEqual(res["text"], "Hello from Zalo")

    @patch("skills.chat.adapters.zalo.eval_js")
    def test_send_zalo_message(self, mock_eval_js) -> None:
        mock_eval_js.side_effect = [True, {"ok": True, "method": "chatController._sendTextMessage"}]
        res = send_zalo_message(101, "g123", "Meeting in 5 mins")
        self.assertTrue(res["ok"])
        self.assertEqual(res["method"], "chatController._sendTextMessage")


if __name__ == "__main__":
    unittest.main()

