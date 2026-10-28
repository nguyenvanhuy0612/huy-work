"""Bridge connector to browserctl/Chrome extension for Outlook Web email retrieval."""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_BRIDGE_URL = os.environ.get("BROWSERCTL_BRIDGE_URL", "http://127.0.0.1:8765")


def call_bridge(
    action: str,
    params: Optional[Dict[str, Any]] = None,
    bridge_url: str = DEFAULT_BRIDGE_URL,
    timeout: float = 10.0,
) -> Any:
    """Executes a command against the local browserctl HTTP daemon."""
    url = f"{bridge_url.rstrip('/')}/command"
    payload = {
        "action": action,
        "params": params or {},
        "client": {"session": "outlook-agent-sync", "source": "outlook-python", "sticky": True},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not data.get("ok", True):
                raise RuntimeError(data.get("error", "Bridge command returned an error"))
            return data.get("result", data)
    except urllib.error.URLError as err:
        raise ConnectionError(
            f"Could not reach browser bridge at {bridge_url}. "
            f"Ensure browserctl or Chrome extension daemon is active on port 8765. Details: {err}"
        ) from err


def find_outlook_tab(bridge_url: str = DEFAULT_BRIDGE_URL) -> Optional[Dict[str, Any]]:
    """Discovers active Outlook Web tabs (Office 365 or Live/Hotmail)."""
    try:
        tabs_data = call_bridge("list_tabs", {}, bridge_url=bridge_url)
    except Exception:
        return None

    tabs = tabs_data.get("tabs", []) if isinstance(tabs_data, dict) else tabs_data
    candidates = []
    for tab in tabs:
        url = tab.get("url", "").lower()
        if any(domain in url for domain in ["outlook.office.com", "outlook.office365.com", "outlook.live.com"]):
            candidates.append(tab)

    if not candidates:
        return None

    # Prefer currently active tab if among candidates
    for tab in candidates:
        if tab.get("active"):
            return tab
    return candidates[0]


def harvest_outlook_emails(tab_id: int, max_items: int = 50, bridge_url: str = DEFAULT_BRIDGE_URL) -> List[Dict[str, Any]]:
    """Harvests email metadata from the active Outlook Web list view."""
    script = r"""
    (() => {
        const results = [];
        // Target list items representing emails in Outlook Web list view
        const items = Array.from(document.querySelectorAll('div[role="option"], div[data-convid]'));
        for (const el of items) {
            try {
                const text = el.innerText || '';
                const lines = text.split('\n').map(s => s.trim()).filter(Boolean);
                if (lines.length < 2) continue;

                const convId = el.getAttribute('data-convid') || el.id || '';
                const isUnread = el.querySelector('[aria-label*="Unread"], [aria-label*="Chưa đọc"]') !== null ||
                                 el.className.includes('unread') ||
                                 (el.getAttribute('aria-label') || '').toLowerCase().includes('unread');

                // Extract sender, subject, and preview from child elements
                const senderEl = el.querySelector('[title], span[class*="sender"], span[class*="author"]');
                const sender = senderEl ? (senderEl.getAttribute('title') || senderEl.textContent) : (lines[0] || 'Unknown');

                const subjectEl = el.querySelector('span[class*="subject"], div[class*="subject"]');
                const subject = subjectEl ? subjectEl.textContent : (lines[1] || 'No Subject');

                const snippet = lines.slice(2, 5).join(' ');
                const dateStr = lines[lines.length - 1] || '';

                results.push({
                    email_id: convId || `${sender}_${subject}_${dateStr}`.slice(0, 80),
                    conversation_id: convId,
                    sender: sender.trim(),
                    subject: subject.trim(),
                    snippet: snippet.trim(),
                    timestamp: dateStr.trim(),
                    is_read: !isUnread,
                });
            } catch (e) {
                // Ignore malformed rows
            }
        }
        return results;
    })()
    """
    res = call_bridge("eval_js", {"tabId": tab_id, "script": script}, bridge_url=bridge_url)
    items = res if isinstance(res, list) else res.get("value", [])
    return items[:max_items]


def read_active_reading_pane(tab_id: int, bridge_url: str = DEFAULT_BRIDGE_URL) -> Dict[str, Any]:
    """Extracts subject and full body text from Outlook reading pane."""
    script = r"""
    (() => {
        const pane = document.querySelector('div[role="main"], div[aria-label*="Reading Pane"], div[aria-label*="Nội dung đọc"]');
        if (!pane) return { error: 'Reading pane not found' };

        const subjectEl = pane.querySelector('h1, h2, [role="heading"]');
        const subject = subjectEl ? subjectEl.textContent.trim() : '';

        const bodyEl = pane.querySelector('div[class*="readingPane"], div[class*="ItemPart"], div[class*="body"]');
        const bodyText = (bodyEl || pane).innerText.trim();

        return {
            subject: subject,
            body: bodyText,
            success: true
        };
    })()
    """
    res = call_bridge("eval_js", {"tabId": tab_id, "script": script}, bridge_url=bridge_url)
    return res if isinstance(res, dict) else {"result": res}
