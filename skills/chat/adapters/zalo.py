"""Zalo Web adapter for chat ingestion and messaging."""

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from skills.common.bridge import DEFAULT_BRIDGE_URL, eval_js, find_tab

_USER_CACHE: Optional[Dict[str, Any]] = None


def clear_user_cache() -> None:
    global _USER_CACHE
    _USER_CACHE = None


def get_cached_user() -> Optional[Dict[str, Any]]:
    global _USER_CACHE
    return _USER_CACHE


def find_zalo_tab(bridge_url: str = DEFAULT_BRIDGE_URL) -> Optional[Dict[str, Any]]:
    return find_tab(
        url_patterns=["chat.zalo.me"],
        title_patterns=["Zalo"],
        bridge_url=bridge_url,
    )


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
    res = eval_js(tab_id, JS_HARVEST_CONVERSATIONS, bridge_url=bridge_url)
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


def normalize_zalo_message(
    raw: Dict[str, Any],
    current_user_id: str = "",
    current_user_name: str = "Me",
    chat_id: str = "",
) -> Optional[Dict[str, Any]]:
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
        "mid": msg_id or cli_msg_id,
        "chat_id": cid,
        "author": author or "Unknown",
        "is_mine": is_mine,
        "time": str(raw.get("time") or raw.get("messageTime") or raw.get("sendDttm") or ""),
        "text": text,
        "message_type": str(raw.get("message_type") or raw.get("msgType") or "Text"),
    }


def harvest_active_messages(
    tab_id: int,
    chat_id: Optional[str] = None,
    current_user_name: Optional[str] = None,
    bridge_url: str = DEFAULT_BRIDGE_URL,
) -> List[Dict[str, Any]]:
    res = eval_js(tab_id, JS_HARVEST_ACTIVE_CHAT_MESSAGES, bridge_url=bridge_url)
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
    """Selects conversation by switching via DOM click or React controller."""
    js = f"""(() => {{
      const items = Array.from(document.querySelectorAll('.msg-item'));
      for (const el of items) {{
        const text = (el.innerText || '').replace(/\\u00a0/g, ' ');
        if (text.includes({json.dumps(conv_id)}) || el.id === {json.dumps(conv_id)}) {{
          const target = el.querySelector('.conv-item, .msg-item__main, div') || el;
          target.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true }}));
          target.dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true }}));
          return true;
        }}
      }}
      return false;
    }})()"""
    res = eval_js(tab_id, js, bridge_url=bridge_url)
    return bool(res)


def send_zalo_message(tab_id: int, chat_id: str, text: str, bridge_url: str = DEFAULT_BRIDGE_URL) -> Dict[str, Any]:
    """Switches to chat_id if necessary and dispatches outbound text to Zalo conversation via React controller."""
    if chat_id:
        if select_conversation(tab_id, chat_id, bridge_url=bridge_url):
            time.sleep(0.3)

    js_send = f"""(() => {{
      const el = document.querySelector('#richInput');
      if (!el) return {{ ok: false, error: 'Input #richInput not found' }};

      const k = Object.keys(el || {{}}).find(key => key.startsWith('__reactInternalInstance') || key.startsWith('__reactFiber'));
      let curr = el ? el[k] : null;
      let chatController = null;
      let addInputText = null;
      let editorController = null;

      while (curr) {{
        if (curr.memoizedProps) {{
          if (!chatController && curr.memoizedProps.chatController) chatController = curr.memoizedProps.chatController;
          if (!addInputText && curr.memoizedProps.addInputText) addInputText = curr.memoizedProps.addInputText;
          if (!editorController && curr.memoizedProps.editorController) editorController = curr.memoizedProps.editorController;
        }}
        curr = curr.return;
      }}

      if (!chatController) return {{ ok: false, error: 'chatController not found on #richInput' }};

      try {{
        if (addInputText) {{
          addInputText({json.dumps(text)});
        }} else if (editorController && typeof editorController.addTextOnly === 'function') {{
          editorController.addTextOnly({json.dumps(text)});
        }} else {{
          el.focus();
          document.execCommand('insertText', false, {json.dumps(text)});
        }}

        chatController._sendTextMessage(true);
        return {{ ok: true, method: 'chatController._sendTextMessage' }};
      }} catch(err) {{
        return {{ ok: false, error: err.toString() }};
      }}
    }})()"""
    res = eval_js(tab_id, js_send, bridge_url=bridge_url)
    if isinstance(res, dict) and res.get("ok"):
        return res
    err = res.get("error", "Unknown error dispatching message") if isinstance(res, dict) else str(res)
    raise RuntimeError(f"Zalo send failed: {err}")

