"""Unit tests for msteam.bridge."""

import sys
import time
import unittest
from pathlib import Path

# Add scripts directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from bridge import (
    clear_auth_cache,
    decode_html_text,
    get_cached_auth,
    normalize_api_message,
)
import bridge


class TestBridge(unittest.TestCase):
    def test_decode_html_text_entities_and_breaks(self) -> None:
        html = "<p>Hello&nbsp;world!<br/>New&lt;line&gt; &amp; quote &quot;test&quot;</p>"
        decoded = decode_html_text(html)
        self.assertEqual(decoded, 'Hello world!\nNew<line> & quote "test"')

    def test_normalize_api_message_standard_rich_text(self) -> None:
        raw = {
            "id": "169999",
            "messagetype": "RichText/Html",
            "originalarrivaltime": "2026-10-21T03:30:00.000Z",
            "from": "8:orgid:user-12345",
            "imdisplayname": "John Doe",
            "content": "<div>Please check <b>server</b> status.</div>",
        }
        norm = normalize_api_message(raw, self_id="user-12345", chat_id="chat99")
        self.assertIsNotNone(norm)
        self.assertEqual(norm["mid"], "169999")
        self.assertEqual(norm["author"], "John Doe")
        self.assertTrue(norm["is_mine"])
        self.assertEqual(norm["text"], "Please check server status.")

    def test_normalize_api_message_ignores_system_events(self) -> None:
        raw = {
            "id": "170000",
            "messagetype": "Event/Call",
            "originalarrivaltime": "2026-10-21T03:35:00.000Z",
            "content": "Call ended",
        }
        norm = normalize_api_message(raw, self_id="user-12345", chat_id="chat99")
        self.assertIsNone(norm)

    def test_auth_cache_ttl_validation(self) -> None:
        clear_auth_cache()
        self.assertIsNone(get_cached_auth())

        # Cache valid for 1 hour
        future_ms = (time.time() + 3600) * 1000
        bridge._AUTH_CACHE = {
            "token": "valid_token",
            "expiresOn": future_ms,
            "region": "apac",
            "selfId": "uid",
        }
        cached = get_cached_auth()
        self.assertIsNotNone(cached)
        self.assertEqual(cached["token"], "valid_token")

        # Cache expiring within 5 minutes is rejected
        near_expiry_ms = (time.time() + 60) * 1000
        bridge._AUTH_CACHE = {
            "token": "expiring_token",
            "expiresOn": near_expiry_ms,
            "region": "apac",
            "selfId": "uid",
        }
        self.assertIsNone(get_cached_auth())
        clear_auth_cache()


if __name__ == "__main__":
    unittest.main()
