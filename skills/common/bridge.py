"""Unified browserctl bridge client for communication skills."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_BRIDGE_URL = os.environ.get("BROWSERCTL_BRIDGE_URL", "http://127.0.0.1:8765")


def call_bridge(
    action: str,
    params: Optional[Dict[str, Any]] = None,
    bridge_url: str = DEFAULT_BRIDGE_URL,
    timeout: float = 10.0,
    session: str = "comm-agent-sync",
) -> Any:
    """Executes an action against the local browserctl HTTP daemon."""
    url = f"{bridge_url.rstrip('/')}/command"
    payload = {
        "action": action,
        "params": params or {},
        "client": {"session": session, "source": "comm-python", "sticky": True},
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
                raise RuntimeError(data.get("error", "Bridge command returned error"))
            return data.get("result", data)
    except urllib.error.URLError as err:
        raise ConnectionError(
            f"Could not reach browser bridge at {bridge_url}. "
            f"Ensure browserctl or Chrome extension daemon is active on port 8765. Details: {err}"
        ) from err


def list_tabs(bridge_url: str = DEFAULT_BRIDGE_URL) -> List[Dict[str, Any]]:
    """Returns a list of all open tabs in connected browser instances."""
    res = call_bridge("list_tabs", bridge_url=bridge_url)
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        return res.get("tabs", [])
    return []


def find_tab(
    url_patterns: Optional[List[str]] = None,
    title_patterns: Optional[List[str]] = None,
    bridge_url: str = DEFAULT_BRIDGE_URL,
) -> Optional[Dict[str, Any]]:
    """Finds an open tab matching any of the specified URL or title substrings."""
    tabs = list_tabs(bridge_url=bridge_url)
    candidates = []

    for tab in tabs:
        url = tab.get("url", "").lower()
        title = tab.get("title", "").lower()

        matched = False
        if url_patterns:
            for pat in url_patterns:
                if pat.lower() in url:
                    matched = True
                    break
        if not matched and title_patterns:
            for pat in title_patterns:
                if pat.lower() in title:
                    matched = True
                    break

        if matched:
            candidates.append(tab)

    if not candidates:
        return None

    # Prefer currently active tab if among candidates
    for c in candidates:
        if c.get("active"):
            return c
    return candidates[0]


def eval_js(tab_id: int, expression: str, bridge_url: str = DEFAULT_BRIDGE_URL) -> Any:
    """Evaluates JavaScript expression in the context of the given tab ID."""
    res = call_bridge("eval_js", {"tabId": tab_id, "expression": expression}, bridge_url=bridge_url)
    if isinstance(res, dict) and "value" in res:
        return res["value"]
    return res

