"""Unit tests for zalo.bridge."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add scripts directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from bridge import (
    clear_user_cache,
    find_zalo_tab,
    get_cached_user,
    harvest_active_messages,
    harvest_conversations,
    normalize_zalo_message,
)
import bridge


class TestZaloBridge(unittest.TestCase):
    def setUp(self) -> None:
        clear_user_cache()

    def tearDown(self) -> None:
        clear_user_cache()

    def test_user_cache(self) -> None:
        self.assertIsNone(get_cached_user())
        bridge._USER_CACHE = {"userId": "123", "displayName": "Tester"}
        self.assertEqual(get_cached_user()["displayName"], "Tester")
        clear_user_cache()
        self.assertIsNone(get_cached_user())

    def test_normalize_zalo_message_standard_text(self) -> None:
        raw = {
            "msg_id": "8416508367172",
            "cli_msg_id": "1792987239631",
            "from_uid": "0",
            "to_uid": "7792528564668089393",
            "message": "Ok nè",
            "time": "1792987239688",
        }
        norm = normalize_zalo_message(
            raw,
            current_user_id="1488132322898755251",
            current_user_name="Nguyễn Văn Huy",
            chat_id="7792528564668089393",
        )
        self.assertIsNotNone(norm)
        self.assertEqual(norm["msg_id"], "8416508367172")
        self.assertEqual(norm["author"], "Nguyễn Văn Huy")
        self.assertTrue(norm["is_mine"])
        self.assertEqual(norm["text"], "Ok nè")

    def test_normalize_zalo_message_from_contact(self) -> None:
        raw = {
            "msgId": "99999",
            "cliMsgId": "88888",
            "fromUid": "106503638855022447",
            "toUid": "1488132322898755251",
            "senderName": "Nguyen Van Luan",
            "text": "Hello there",
            "time": "1792987239000",
        }
        norm = normalize_zalo_message(
            raw,
            current_user_id="1488132322898755251",
            current_user_name="Nguyễn Văn Huy",
            chat_id="106503638855022447",
        )
        self.assertIsNotNone(norm)
        self.assertEqual(norm["author"], "Nguyen Van Luan")
        self.assertFalse(norm["is_mine"])
        self.assertEqual(norm["text"], "Hello there")

    def test_normalize_zalo_message_dict_content(self) -> None:
        raw = {
            "msg_id": "123",
            "from_uid": "0",
            "message": {"title": "sendBubbleMessage", "description": "Cuộc gọi"},
            "time": "1000",
        }
        norm = normalize_zalo_message(raw, chat_id="c1")
        self.assertEqual(norm["text"], "sendBubbleMessage")

    @patch("bridge.call_bridge")
    def test_find_zalo_tab(self, mock_call: MagicMock) -> None:
        mock_call.return_value = {
            "tabs": [
                {"id": 1, "url": "https://google.com", "title": "Google"},
                {"id": 414190273, "url": "https://chat.zalo.me/", "title": "Zalo - Nguyễn Văn Huy"},
            ]
        }
        tab = find_zalo_tab()
        self.assertIsNotNone(tab)
        self.assertEqual(tab["id"], 414190273)

    @patch("bridge.eval_zalo_js")
    def test_harvest_conversations(self, mock_eval: MagicMock) -> None:
        mock_eval.return_value = {
            "user": {"userId": "u1", "displayName": "Tester"},
            "conversations": [
                {
                    "chat_id": "c1",
                    "title": "Group A",
                    "is_group": True,
                    "category": "group",
                    "last_activity": "1000",
                    "unread_count": 0,
                    "members": ["Tester", "Alice"],
                    "avatar": "",
                    "last_message": {"msg_id": "m1", "text": "Hi", "time": "1000"},
                }
            ],
        }
        user, convs = harvest_conversations(414190273)
        self.assertEqual(user["displayName"], "Tester")
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["title"], "Group A")
        self.assertEqual(get_cached_user()["userId"], "u1")

    @patch("bridge.eval_zalo_js")
    def test_harvest_active_messages(self, mock_eval: MagicMock) -> None:
        mock_eval.return_value = {
            "count": 1,
            "messages": [
                {
                    "msg_id": "m1",
                    "cli_msg_id": "c1",
                    "from_uid": "0",
                    "to_uid": "user2",
                    "author": "",
                    "text": "Hello",
                    "time": "1000",
                    "message_type": "Text",
                    "is_mine": True,
                }
            ],
        }
        msgs = harvest_active_messages(414190273, chat_id="user2", current_user_name="Tester")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["author"], "Tester")
        self.assertTrue(msgs[0]["is_mine"])


if __name__ == "__main__":
    unittest.main()
