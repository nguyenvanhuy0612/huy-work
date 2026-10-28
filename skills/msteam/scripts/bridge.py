"""Bridge connector to browserctl/Chrome extension for Teams message retrieval."""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_BRIDGE_URL = os.environ.get("BROWSERCTL_BRIDGE_URL", "http://127.0.0.1:8765")
_AUTH_CACHE: Optional[Dict[str, Any]] = None


def clear_auth_cache() -> None:
    """Clears the cached authentication credentials."""
    global _AUTH_CACHE
    _AUTH_CACHE = None


def get_cached_auth() -> Optional[Dict[str, Any]]:
    """Returns cached auth if present and not expiring within 5 minutes."""
    global _AUTH_CACHE
    if not _AUTH_CACHE:
        return None
    expires_on = _AUTH_CACHE.get("expiresOn", 0)
    # Check if expiration is at least 5 minutes in the future
    if time.time() * 1000 < (expires_on - 5 * 60 * 1000):
        return _AUTH_CACHE
    _AUTH_CACHE = None
    return None


def call_bridge(action: str, params: Optional[Dict[str, Any]] = None, bridge_url: str = DEFAULT_BRIDGE_URL) -> Any:
    url = f"{bridge_url.rstrip('/')}/command"
    payload = {
        "action": action,
        "params": params or {},
        "client": {"session": "msteam-agent-sync", "source": "msteam-python", "sticky": True},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not data.get("ok", True):
                raise RuntimeError(data.get("error", "Bridge command returned error"))
            return data.get("result", data)
    except urllib.error.URLError as err:
        raise ConnectionError(f"Could not reach browser bridge at {bridge_url}: {err}") from err


def find_teams_tab(bridge_url: str = DEFAULT_BRIDGE_URL) -> Optional[Dict[str, Any]]:
    res = call_bridge("list_tabs", bridge_url=bridge_url)
    tabs = res.get("tabs", [])
    for tab in tabs:
        url = tab.get("url", "")
        title = tab.get("title", "")
        if "teams.cloud.microsoft" in url or "teams.microsoft.com" in url or "Microsoft Teams" in title:
            return tab
    return None


JS_HARVEST_TEAMS_AUTH = r"""
(async () => {
  let token = null;
  let selfId = '';

  // Strategy 1: React Fiber Auth Service (handles dynamic decryption and silent token refresh)
  try {
    const root = document.querySelector('#app');
    const fiberKey = Object.keys(root || {}).find(k => k.startsWith('__reactContainer') || k.startsWith('__reactFiber'));
    if (fiberKey && root) {
      let curr = root[fiberKey];
      const queue = [curr];
      let authService = null;
      while (queue.length > 0) {
        const node = queue.shift();
        if (!node) continue;
        const props = node.memoizedProps;
        if (props && props.mediaAuthService && props.mediaAuthService._authenticationService) {
          authService = props.mediaAuthService._authenticationService;
          break;
        }
        if (node.child) queue.push(node.child);
        if (node.sibling) queue.push(node.sibling);
      }
      if (authService && typeof authService.acquireToken === 'function') {
        const res = await authService.acquireToken('https://ic3.teams.office.com');
        if (typeof res === 'string' && res.startsWith('ey')) {
          token = res;
          const user = typeof authService.getUser === 'function' ? authService.getUser() : null;
          selfId = user?.id || '';
        }
      }
    }
  } catch (e) {}

  // Strategy 2: Fallback to localStorage plaintext tokens
  if (!token) {
    const entries = Object.keys(localStorage).filter(k => k.includes('accesstoken'))
      .map(k => { try { return JSON.parse(localStorage.getItem(k)); } catch(e){ return null; } }).filter(Boolean);
    const tokens = entries.filter(o => o.target?.includes('https://ic3.teams.office.com/') &&
      Number(o.expiresOn) * 1000 > Date.now()).sort((a, b) => Number(b.expiresOn) - Number(a.expiresOn));
    if (tokens[0]?.secret) {
      token = tokens[0].secret;
      selfId = tokens[0].homeAccountId?.split('.')[0] || '';
    }
  }

  if (!token) {
    return { error: 'AUTH_EXPIRED', message: 'Teams messaging token missing or expired; please refresh Teams tab.' };
  }

  const regionKey = Object.keys(localStorage).find(k => k.endsWith('.Discover.SKYPE-TOKEN'));
  const region = regionKey ? (JSON.parse(localStorage.getItem(regionKey))?.item?.userDetails?.region || null) : 'apac';
  const expiresOn = Date.now() + 45 * 60 * 1000;

  return {
    token,
    expiresOn,
    region: region || 'apac',
    selfId: selfId || ''
  };
})()
"""

JS_DISCOVER_SIDEBAR_CHATS = r"""
(() => {
  const chatListNodes = Array.from(document.querySelectorAll('[data-item-type="chat"], [data-item-type="muted-chat"]'));
  const sidebarChats = [];
  chatListNodes.forEach((node, idx) => {
    const isUnread = node.getAttribute('aria-labelledby')?.includes('chat_list_unread_text') || !!node.querySelector('[aria-label*="unread" i]');
    const titleEl = node.querySelector('[id^="title-chat-list-item_"]');
    const title = titleEl ? titleEl.innerText.trim() : (node.querySelector('h3, span[title]')?.innerText?.trim() || '');
    if (!title) return;
    const chatId = titleEl?.id.replace('title-chat-list-item_', '') || '';
    sidebarChats.push({ index: idx, title, chatId, isUnread });
  });
  return { sidebarChats };
})()
"""


def decode_html_text(html: str) -> str:
    html = re.sub(r"<br\s*/?>|</(?:p|div|li)>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]*>", "", html)
    entities = {
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&apos;": "'",
        "&nbsp;": " ",
    }
    for ent, val in entities.items():
        html = html.replace(ent, val)
    return html.strip()


def normalize_api_message(raw: Dict[str, Any], self_id: str, chat_id: str) -> Optional[Dict[str, Any]]:
    msg_type = raw.get("messagetype", "")
    if not re.match(r"^(Text|RichText(/|$))", msg_type):
        return None
    mid = raw.get("id")
    orig_time = raw.get("originalarrivaltime")
    if not mid or not orig_time:
        return None

    html = raw.get("content") or ""
    text = decode_html_text(html)

    card_match = re.search(r'<Swift\s+b64="([^"]+)"', html, re.IGNORECASE)
    if card_match:
        import base64
        try:
            card_content = json.loads(base64.b64decode(card_match.group(1)).decode("utf-8"))
            texts: List[str] = []
            def walk(val: Any) -> None:
                if not val or not isinstance(val, (dict, list)):
                    return
                if isinstance(val, dict):
                    if isinstance(val.get("text"), str):
                        texts.append(val["text"])
                    if isinstance(val.get("title"), str):
                        texts.append(val["title"])
                    for child in val.values():
                        walk(child)
                elif isinstance(val, list):
                    for item in val:
                        walk(item)
            walk(card_content)
            if texts:
                text = "\n".join(texts)
        except Exception:
            pass

    sender = (raw.get("from") or "").split("/").pop()
    author = raw.get("imdisplayname") or sender or "Unknown"
    is_mine = sender == f"8:orgid:{self_id}" or sender == f"8:teamsvisitor:{self_id}"

    return {
        "mid": str(mid),
        "chat_id": chat_id,
        "author": author,
        "is_mine": is_mine,
        "time": orig_time,
        "text": text,
        "content_html": html,
        "message_type": msg_type,
        "observed_at": orig_time,
    }


def scan_sidebar_chats(tab_id: int, bridge_url: str = DEFAULT_BRIDGE_URL) -> List[Dict[str, Any]]:
    eval_res = call_bridge("eval_js", {"tabId": tab_id, "expression": JS_DISCOVER_SIDEBAR_CHATS}, bridge_url=bridge_url)
    val = eval_res.get("value") or {}
    return val.get("sidebarChats", [])


def harvest_teams_auth(
    tab_id: int,
    bridge_url: str = DEFAULT_BRIDGE_URL,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Harvests Bearer token and region from Teams tab with in-memory caching."""
    global _AUTH_CACHE
    if not force_refresh:
        cached = get_cached_auth()
        if cached:
            return cached

    eval_res = call_bridge("eval_js", {"tabId": tab_id, "expression": JS_HARVEST_TEAMS_AUTH}, bridge_url=bridge_url)
    val = eval_res.get("value") or {}
    if val.get("error"):
        if val["error"] == "AUTH_EXPIRED":
            raise RuntimeError("AUTH_EXPIRED: Teams authentication token missing or expired; please refresh Teams tab.")
        raise RuntimeError(f"Teams auth harvest failed: {val.get('message', val['error'])}")

    if not val.get("token") or not val.get("region"):
        raise RuntimeError("Teams auth harvesting returned incomplete credentials.")

    _AUTH_CACHE = {
        "token": val["token"],
        "expiresOn": val.get("expiresOn", 0),
        "region": val["region"],
        "selfId": val.get("selfId", ""),
    }
    return _AUTH_CACHE


def fetch_teams_messages_direct(
    auth: Dict[str, Any],
    chat_id: str,
    next_url: Optional[str] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """Fetches messages directly from Teams ChatSvc outside the browser context."""
    token = auth.get("token")
    region = auth.get("region")
    self_id = auth.get("selfId", "")
    if not token or not region:
        raise ValueError("Auth payload missing token or region")

    prefix = f"/api/chatsvc/{region}/v1/users/ME/conversations/"
    expected_path = f"{prefix}{chat_id}/messages"
    origin = "https://teams.cloud.microsoft"

    if next_url:
        parsed = urllib.parse.urlparse(next_url)
        if parsed.scheme and parsed.netloc and f"{parsed.scheme}://{parsed.netloc}" != origin:
            raise ValueError(f"Rejected unexpected Teams pagination origin: {parsed.netloc}")
        if urllib.parse.unquote(parsed.path) != expected_path:
            raise ValueError(f"Rejected unexpected Teams pagination path: {parsed.path}")
        url = next_url
    else:
        url = f"{origin}{prefix}{urllib.parse.quote(chat_id)}/messages?pageSize=50"

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data.get("messages"), list):
                raise RuntimeError(f"Teams API response messages array missing for {chat_id}")
            return {
                "selfId": self_id,
                "messages": data.get("messages", []),
                "backwardLink": data.get("_metadata", {}).get("backwardLink"),
                "syncState": data.get("_metadata", {}).get("syncState"),
            }
    except urllib.error.HTTPError as err:
        if err.code == 401:
            clear_auth_cache()
            raise RuntimeError("AUTH_EXPIRED: Teams authentication expired (HTTP 401).") from err
        raise RuntimeError(f"Teams API HTTP {err.code}: {err.reason}") from err
    except urllib.error.URLError as err:
        raise ConnectionError(f"Could not reach Teams API: {err}") from err


def fetch_api_messages(
    tab_id: int,
    chat_id: str,
    next_url: Optional[str] = None,
    bridge_url: str = DEFAULT_BRIDGE_URL,
) -> Dict[str, Any]:
    """Compatibility wrapper: harvests auth via browser bridge once, then calls direct API."""
    auth = harvest_teams_auth(tab_id, bridge_url=bridge_url)
    return fetch_teams_messages_direct(auth, chat_id, next_url=next_url)
