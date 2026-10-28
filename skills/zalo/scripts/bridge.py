"""Bridge connector to browserctl/Chrome extension for Zalo message retrieval."""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_BRIDGE_URL = os.environ.get("BROWSERCTL_BRIDGE_URL", "http://127.0.0.1:8765")
_USER_CACHE: Optional[Dict[str, Any]] = None


def clear_user_cache() -> None:
    """Clears cached current user metadata."""
    global _USER_CACHE
    _USER_CACHE = None


def get_cached_user() -> Optional[Dict[str, Any]]:
    """Returns cached user metadata if present."""
    global _USER_CACHE
    return _USER_CACHE


def call_bridge(action: str, params: Optional[Dict[str, Any]] = None, bridge_url: str = DEFAULT_BRIDGE_URL) -> Any:
    url = f"{bridge_url.rstrip('/')}/command"
    payload = {
        "action": action,
        "params": params or {},
        "client": {"session": "zalo-agent-sync", "source": "zalo-python", "sticky": True},
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


def find_zalo_tab(bridge_url: str = DEFAULT_BRIDGE_URL) -> Optional[Dict[str, Any]]:
    """Finds active Zalo tab in connected Chrome instances."""
    res = call_bridge("list_tabs", bridge_url=bridge_url)
    tabs = res.get("tabs", [])
    for tab in tabs:
        url = tab.get("url", "")
        title = tab.get("title", "")
        if "chat.zalo.me" in url or "Zalo" in title:
            return tab
    return None


def eval_zalo_js(tab_id: int, expression: str, bridge_url: str = DEFAULT_BRIDGE_URL) -> Any:
    """Evaluates JavaScript expression in the context of the Zalo tab."""
    res = call_bridge("eval_js", {"tabId": tab_id, "expression": expression}, bridge_url=bridge_url)
    if isinstance(res, dict) and "value" in res:
        return res["value"]
    return res


JS_HARVEST_CONVERSATIONS = r"""
(() => {
  const item = document.querySelector('.msg-item');
  if (!item) return { error: 'No .msg-item found' };
  
  const k = Object.keys(item).find(key => key.startsWith('__reactInternalInstance') || key.startsWith('__reactFiber'));
  let curr = item[k];
  let convlistController = null;
  let state = null;
  let user = null;
  
  while (curr) {
    if (curr.memoizedProps) {
      if (!convlistController && curr.memoizedProps.convlistController) {
        convlistController = curr.memoizedProps.convlistController;
      }
      if (!state && curr.memoizedProps.state) {
        state = curr.memoizedProps.state;
      }
      if (!user && curr.memoizedProps.user) {
        user = curr.memoizedProps.user;
      }
    }
    curr = curr.return;
  }
  
  if (!convlistController) return { error: 'convlistController not found' };
  
  const pm = convlistController._pm || convlistController.previewManager;
  const rawPreviews = pm ? pm.getAllPreviewsSync() : {};
  const previews = Array.isArray(rawPreviews) ? rawPreviews : Object.values(rawPreviews || {});
  const contacts = (state && state.contacts) || {};
  const groups = (state && state.groups) || {};
  const listVisible = convlistController.listVisible || [];
  const listAll = convlistController.listRawAll || listVisible;
  const targetIds = listVisible.length > 0 ? listVisible : listAll;
  
  const currentUserId = user ? String(user.userId || '') : '';
  const result = [];
  
  for (const id of targetIds) {
    const isGroup = id.startsWith('g');
    const groupInfo = isGroup ? groups[id] : null;
    const contactInfo = !isGroup ? contacts[id] : null;
    
    let preview = previews.find(p => p && (p.convId === id || p.toUid === id));
    
    let title = '';
    let avatar = '';
    let members = [];
    
    if (isGroup && groupInfo) {
      title = groupInfo.displayName || ('Group ' + id);
      avatar = groupInfo.avatar || '';
      members = (groupInfo.topMember || []).map(m => m.dName || m.id);
    } else if (contactInfo) {
      title = contactInfo.displayName || contactInfo.zaloName || '';
      avatar = contactInfo.avatar || '';
    }
    
    if (!title && preview) {
      title = preview.dName || '';
    }
    if (!title) {
      title = 'Conversation ' + id;
    }
    
    let lastMsgText = '';
    let lastMsgTime = '';
    let author = '';
    let msgId = '';
    let cliMsgId = '';
    let isMine = false;
    let fromUid = '';
    let toUid = id;
    
    if (preview) {
      msgId = String(preview.msgId || '');
      cliMsgId = String(preview.cliMsgId || '');
      fromUid = String(preview.fromUid || '');
      toUid = String(preview.toUid || id);
      
      if (typeof preview.message === 'string') {
        lastMsgText = preview.message;
      } else if (preview.message && typeof preview.message === 'object') {
        lastMsgText = preview.message.title || preview.message.description || '[Attachment/Media]';
      }
      
      lastMsgTime = String(preview.messageTime || '');
      author = preview.dName || '';
      isMine = (fromUid === '0' || (currentUserId !== '' && fromUid === currentUserId));
      if (isMine && user) {
        author = user.displayName || 'Me';
      }
    }
    
    result.push({
      chat_id: id,
      title: title,
      is_group: isGroup,
      category: isGroup ? 'group' : (id === '0' || id.startsWith('cloud') ? 'cloud' : 'direct'),
      last_activity: lastMsgTime,
      unread_count: 0,
      members: members,
      avatar: avatar,
      last_message: {
        msg_id: msgId,
        cli_msg_id: cliMsgId,
        chat_id: id,
        author: author,
        from_uid: fromUid,
        to_uid: toUid,
        text: lastMsgText,
        time: lastMsgTime,
        is_mine: isMine
      }
    });
  }
  
  return {
    user: user ? {
      userId: user.userId,
      displayName: user.displayName,
      phoneNumber: user.phoneNumber,
      avatar: user.avatar
    } : null,
    conversations: result
  };
})()
"""

JS_HARVEST_ACTIVE_CHAT_MESSAGES = r"""
(() => {
  const chatMsgs = Array.from(document.querySelectorAll('.chat-message') || []);
  const result = [];
  for (const m of chatMsgs) {
    const k = Object.keys(m).find(key => key.startsWith('__reactInternalInstance') || key.startsWith('__reactFiber'));
    let curr = m[k];
    let d = null;
    let senderName = '';
    while (curr) {
      if (curr.memoizedProps) {
        if (!d && curr.memoizedProps.data && curr.memoizedProps.data.msgId) {
          d = curr.memoizedProps.data;
        }
        if (!senderName && curr.memoizedProps.senderName) {
          senderName = curr.memoizedProps.senderName;
        }
      }
      curr = curr.return;
    }
    if (d) {
      let text = d.message || '';
      if (typeof text === 'object') {
        text = text.title || text.description || JSON.stringify(text);
      }
      result.push({
        msg_id: String(d.msgId || ''),
        cli_msg_id: String(d.cliMsgId || ''),
        from_uid: String(d.fromUid || ''),
        to_uid: String(d.toUid || ''),
        author: senderName || d.dName || '',
        text: text,
        time: String(d.sendDttm || d.serverTime || d.time || ''),
        message_type: String(d.msgType || 'Text'),
        is_mine: (d.fromUid === '0' || d.isMine || false)
      });
    }
  }
  return { count: result.length, messages: result };
})()
"""


def harvest_conversations(tab_id: int, bridge_url: str = DEFAULT_BRIDGE_URL) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Harvests user profile and full list of conversations with latest previews."""
    res = eval_zalo_js(tab_id, JS_HARVEST_CONVERSATIONS, bridge_url=bridge_url)
    if not isinstance(res, dict):
        return None, []
    if "error" in res:
        raise RuntimeError(f"Zalo in-page harvester error: {res['error']}")
    user_info = res.get("user")
    if user_info:
        global _USER_CACHE
        _USER_CACHE = user_info
    convs = res.get("conversations", [])
    return user_info, convs


def harvest_active_messages(
    tab_id: int,
    chat_id: Optional[str] = None,
    current_user_name: Optional[str] = None,
    bridge_url: str = DEFAULT_BRIDGE_URL,
) -> List[Dict[str, Any]]:
    """Harvests messages from active open chat window in Zalo."""
    res = eval_zalo_js(tab_id, JS_HARVEST_ACTIVE_CHAT_MESSAGES, bridge_url=bridge_url)
    if not isinstance(res, dict):
        return []
    raw_msgs = res.get("messages", [])
    normalized = []
    user = get_cached_user() or {}
    my_name = current_user_name or user.get("displayName") or "Me"
    my_id = str(user.get("userId") or "")

    for m in raw_msgs:
        norm = normalize_zalo_message(m, current_user_id=my_id, current_user_name=my_name, chat_id=chat_id or m.get("to_uid", ""))
        if norm:
            normalized.append(norm)
    return normalized


def select_conversation(tab_id: int, conv_id: str, bridge_url: str = DEFAULT_BRIDGE_URL) -> bool:
    """Instructs Zalo tab to switch active chat to conv_id."""
    js = f"""(() => {{
      const item = document.querySelector('.msg-item');
      if (!item) return false;
      const k = Object.keys(item).find(key => key.startsWith('__reactInternalInstance') || key.startsWith('__reactFiber'));
      let curr = item[k];
      while (curr) {{
        if (curr.memoizedProps && curr.memoizedProps.convlistController) {{
          const c = curr.memoizedProps.convlistController;
          if (typeof c.selectConversation === 'function') {{
            c.selectConversation({json.dumps(conv_id)});
            return true;
          }}
        }}
        curr = curr.return;
      }}
      return false;
    }})()"""
    res = eval_zalo_js(tab_id, js, bridge_url=bridge_url)
    return bool(res)


def normalize_zalo_message(
    raw: Dict[str, Any],
    current_user_id: str = "",
    current_user_name: str = "Me",
    chat_id: str = "",
) -> Optional[Dict[str, Any]]:
    """Normalizes raw in-page message object into standard DB format."""
    msg_id = str(raw.get("msg_id") or raw.get("msgId") or "").strip()
    cli_msg_id = str(raw.get("cli_msg_id") or raw.get("cliMsgId") or "").strip()
    cid = str(chat_id or raw.get("chat_id") or raw.get("to_uid") or raw.get("toUid") or "").strip()
    from_uid = str(raw.get("from_uid") or raw.get("fromUid") or "").strip()
    to_uid = str(raw.get("to_uid") or raw.get("toUid") or cid).strip()

    is_mine = bool(raw.get("is_mine") or raw.get("isMine") or from_uid == "0" or (current_user_id and from_uid == current_user_id))
    author = raw.get("author") or raw.get("senderName") or raw.get("dName") or ""
    if is_mine:
        author = current_user_name

    text = raw.get("text") or raw.get("message") or ""
    if isinstance(text, dict):
        text = text.get("title") or text.get("description") or json.dumps(text, ensure_ascii=False)

    return {
        "msg_id": msg_id,
        "cli_msg_id": cli_msg_id,
        "chat_id": cid,
        "author": author or "Unknown",
        "from_uid": from_uid,
        "to_uid": to_uid,
        "is_mine": is_mine,
        "time": str(raw.get("time") or raw.get("messageTime") or raw.get("sendDttm") or ""),
        "text": text,
        "message_type": str(raw.get("message_type") or raw.get("msgType") or "Text"),
    }
