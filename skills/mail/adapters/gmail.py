"""Gmail Web adapter with multi-account verification, ingestion, and dispatch."""

import base64
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from skills.common.bridge import DEFAULT_BRIDGE_URL, eval_js, list_tabs

DEFAULT_GMAIL_ACCOUNT = "nguyenvanhuy0612@gmail.com"


def get_tab_account(tab_id: int, bridge_url: str = DEFAULT_BRIDGE_URL) -> Optional[str]:
    """Inspects a Gmail tab to determine the authenticated account email address."""
    check_js = r"""
    (() => {
        // 1. window.GLOBALS check
        if (window.GLOBALS && Array.isArray(window.GLOBALS)) {
            for (let item of window.GLOBALS) {
                if (typeof item === 'string' && item.includes('@') && !item.includes(' ')) {
                    return item.toLowerCase();
                }
            }
        }
        // 2. Avatar / Header aria-label
        const accEl = document.querySelector('a[aria-label*="@"], [aria-label*="Tài khoản Google"], [aria-label*="Google Account"]');
        if (accEl) {
            const label = accEl.getAttribute('aria-label') || '';
            const match = label.match(/([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})/);
            if (match) return match[1].toLowerCase();
        }
        // 3. Document title
        const titleMatch = document.title.match(/([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})/);
        if (titleMatch) return titleMatch[1].toLowerCase();
        return null;
    })()
    """
    try:
        val = eval_js(tab_id, check_js, bridge_url=bridge_url)
        return str(val).strip().lower() if val else None
    except Exception:
        return None


def list_gmail_accounts(bridge_url: str = DEFAULT_BRIDGE_URL) -> List[Dict[str, Any]]:
    """Returns a list of all open Gmail tabs with their verified account emails."""
    tabs = list_tabs(bridge_url=bridge_url)
    gmail_tabs = []
    for tab in tabs:
        url = tab.get("url", "")
        title = tab.get("title", "")
        if "mail.google.com" in url or "Gmail" in title:
            acc = get_tab_account(tab["id"], bridge_url=bridge_url)
            gmail_tabs.append({
                "tab_id": tab["id"],
                "url": url,
                "title": title,
                "account": acc,
                "active": tab.get("active", False),
            })
    return gmail_tabs


def find_gmail_tab(
    account: Optional[str] = None,
    bridge_url: str = DEFAULT_BRIDGE_URL,
) -> Optional[Dict[str, Any]]:
    """Finds an active Gmail tab matching the requested account email."""
    tabs = list_tabs(bridge_url=bridge_url)
    candidates = []
    for tab in tabs:
        url = tab.get("url", "")
        title = tab.get("title", "")
        if "mail.google.com" in url or "Gmail" in title:
            candidates.append(tab)

    if not candidates:
        return None

    if not account:
        # Default: pick active tab if present, else first
        for c in candidates:
            if c.get("active"):
                return c
        return candidates[0]

    target = account.strip().lower()
    # 1. Title/URL fast check
    for c in candidates:
        if target in c.get("title", "").lower() or target in c.get("url", "").lower():
            return c

    # 2. In-depth DOM verification
    for c in candidates:
        tab_acc = get_tab_account(c["id"], bridge_url=bridge_url)
        if tab_acc and tab_acc == target:
            return c

    return None


def parse_thread_id_from_jslog(jslog: str) -> Optional[str]:
    """Decodes canonical Gmail thread ID from base64 packet inside jslog."""
    if not jslog:
        return None
    for part in jslog.split(";"):
        part = part.strip()
        if not part.startswith("1:"):
            continue
        b64_str = part[2:].replace(".", "=")
        padding = (4 - len(b64_str) % 4) % 4
        b64_str += "=" * padding
        try:
            decoded = base64.b64decode(b64_str).decode("utf-8", errors="ignore")
            match = re.search(r"#thread-[af]:([0-9a-fA-F]+)", decoded)
            if match:
                return match.group(1)
        except Exception:
            continue
    return None


INBOX_CATEGORIES = [
    ("primary", [":24", "chính", "chính", "primary"]),
    ("promotions", [":25", "quảng cáo", "promotions"]),
    ("social", [":26", "mạng xã hội", "xã hội", "social"]),
    ("updates", [":27", "nội dung cập nhật", "cập nhật", "updates"]),
    ("forums", [":28", "diễn đàn", "forums"]),
]


def switch_inbox_category(tab_id: int, category: str, bridge_url: str = DEFAULT_BRIDGE_URL) -> bool:
    """Switches active inbox category tab (primary, promotions, social, updates, forums)."""
    target_key = category.lower().strip()
    keywords = [target_key]
    for name, aliases in INBOX_CATEGORIES:
        if name == target_key or target_key in aliases:
            keywords = aliases
            break

    js = f"""
    (() => {{
        const keywords = {json.dumps(keywords)};
        const tabs = Array.from(document.querySelectorAll('div[role="tab"]'));
        const target = tabs.find(t => {{
            const id = t.id || '';
            const aria = (t.getAttribute('aria-label') || '').normalize('NFC').toLowerCase();
            const text = (t.textContent || '').normalize('NFC').toLowerCase();
            return keywords.some(k => id === k || aria.includes(k) || text.includes(k));
        }});
        if (!target) return false;

        const opts = {{ bubbles: true, cancelable: true, view: window }};
        target.dispatchEvent(new MouseEvent('mousedown', opts));
        target.dispatchEvent(new MouseEvent('mouseup', opts));
        target.dispatchEvent(new MouseEvent('click', opts));
        return true;
    }})()
    """
    res = eval_js(tab_id, js, bridge_url=bridge_url)
    return bool(res)


def harvest_visible_inbox_rows(tab_id: int, bridge_url: str = DEFAULT_BRIDGE_URL) -> List[Dict[str, Any]]:
    """Harvests rows from the currently rendered inbox panel."""
    script = r"""
    (() => {
        const panels = Array.from(document.querySelectorAll('div[role="tabpanel"]'));
        let visible = panels.find(p => p.style.display !== 'none');
        const root = visible || document;
        const rows = Array.from(root.querySelectorAll('tr.zA') || []);
        const results = [];
        for (const row of rows) {
            try {
                const jslog = row.getAttribute('jslog') || '';
                const isUnread = row.classList.contains('zE');

                const senderEl = row.querySelector('.yX .yW span[email], .yX .yW .zF, .yP, .bqe');
                const senderEmail = senderEl ? (senderEl.getAttribute('email') || '') : '';
                const senderName = senderEl ? (senderEl.getAttribute('name') || senderEl.textContent.trim()) : 'Unknown';

                const subjEl = row.querySelector('.bog span, .bog');
                const subject = subjEl ? subjEl.textContent.trim() : 'No Subject';

                const snipEl = row.querySelector('.y2');
                let snippet = snipEl ? snipEl.textContent.trim() : '';
                if (snippet.startsWith('- ')) snippet = snippet.slice(2).trim();

                const dateEl = row.querySelector('.xW span[title], .xW span[aria-label]');
                const dateText = dateEl ? (dateEl.getAttribute('title') || dateEl.getAttribute('aria-label') || dateEl.textContent.trim()) : '';

                results.push({
                    jslog: jslog,
                    sender_email: senderEmail,
                    sender_name: senderName,
                    subject: subject,
                    snippet: snippet,
                    raw_date: dateText,
                    is_read: !isUnread
                });
            } catch (e) {}
        }
        return results;
    })()
    """
    raw_list = eval_js(tab_id, script, bridge_url=bridge_url)
    return raw_list if isinstance(raw_list, list) else []


def harvest_gmail_threads(
    tab_id: int,
    max_items: int = 50,
    category: str = "all",
    bridge_url: str = DEFAULT_BRIDGE_URL,
) -> List[Dict[str, Any]]:
    """Harvests thread list items from active Gmail inbox view across categories."""
    categories_to_harvest = [c[0] for c in INBOX_CATEGORIES] if category == "all" else [category]
    all_results = []
    seen_ids = set()
    import time

    per_cat_limit = max_items if category != "all" else max(10, max_items // len(categories_to_harvest))

    for cat in categories_to_harvest:
        switch_inbox_category(tab_id, cat, bridge_url=bridge_url)
        time.sleep(0.6)
        raw_list = harvest_visible_inbox_rows(tab_id, bridge_url=bridge_url)

        for item in raw_list[:per_cat_limit]:
            tid = parse_thread_id_from_jslog(item.get("jslog", ""))
            email_id = tid or f"{item.get('sender_email')}_{item.get('subject')}_{item.get('raw_date')}"
            if email_id in seen_ids:
                continue
            seen_ids.add(email_id)

            all_results.append({
                "email_id": email_id,
                "conversation_id": tid or email_id,
                "sender": f"{item.get('sender_name')} <{item.get('sender_email')}>" if item.get("sender_email") else item.get("sender_name", "Unknown"),
                "subject": item.get("subject", "No Subject"),
                "snippet": item.get("snippet", ""),
                "timestamp": item.get("raw_date", ""),
                "is_read": item.get("is_read", True),
                "category": cat,
            })

    # Always return to primary tab
    if category == "all" or len(categories_to_harvest) > 1:
        switch_inbox_category(tab_id, "primary", bridge_url=bridge_url)

    return all_results[:max_items]


def read_open_gmail_thread(tab_id: int, bridge_url: str = DEFAULT_BRIDGE_URL) -> Dict[str, Any]:
    """Reads messages and subject from an currently opened Gmail thread view."""
    script = r"""
    (() => {
        const subjEl = document.querySelector('h2.hP');
        const subject = subjEl ? subjEl.textContent.trim() : '';

        const msgNodes = Array.from(document.querySelectorAll('.adn') || []);
        const messages = [];

        for (const m of msgNodes) {
            const senderEl = m.querySelector('.gD');
            const sender = senderEl ? (senderEl.getAttribute('email') || senderEl.textContent.trim()) : 'Unknown';
            const dateEl = m.querySelector('.g3');
            const dateStr = dateEl ? (dateEl.getAttribute('title') || dateEl.textContent.trim()) : '';
            const bodyEl = m.querySelector('.a3s.aiL, .ii.gt');
            const body = bodyEl ? bodyEl.innerText.trim() : '';

            messages.push({
                sender: sender,
                date: dateStr,
                body: body
            });
        }
        return {
            subject: subject,
            messages: messages
        };
    })()
    """
    res = eval_js(tab_id, script, bridge_url=bridge_url)
    return res if isinstance(res, dict) else {}


def compose_gmail_email(
    tab_id: int,
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    send_now: bool = False,
    bridge_url: str = DEFAULT_BRIDGE_URL,
) -> Dict[str, Any]:
    """Opens compose window in Gmail, fills recipient, subject, body, and optionally sends."""
    script = f"""
    (() => {{
        // 1. Click Compose button
        const compBtn = document.querySelector('div[role="button"][gh="cm"], .T-I.T-I-KE.L3, div[aria-label*="Compose"], div[aria-label*="Soạn thư"]');
        if (compBtn) compBtn.click();

        return new Promise((resolve) => {{
            setTimeout(() => {{
                // 2. Fill To
                const toInput = document.querySelector('input[peoplekit-id], input[name="to"], textarea[name="to"], div[aria-label*="To"] input');
                if (toInput) {{
                    toInput.focus();
                    document.execCommand('insertText', false, {json.dumps(to)});
                    toInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}

                // Optional CC
                const ccVal = {json.dumps(cc)};
                if (ccVal) {{
                    const ccBtn = document.querySelector('span[role="link"][data-tooltip*="Cc"], span[aria-label*="Cc"]');
                    if (ccBtn) ccBtn.click();
                    const ccInput = document.querySelector('input[name="cc"], textarea[name="cc"], div[aria-label*="Cc"] input');
                    if (ccInput) {{
                        ccInput.focus();
                        document.execCommand('insertText', false, ccVal);
                        ccInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    }}
                }}

                // 3. Fill Subject
                const subjInput = document.querySelector('input[name="subjectbox"], input[placeholder*="Subject"], input[placeholder*="Chủ đề"]');
                if (subjInput) {{
                    subjInput.focus();
                    document.execCommand('insertText', false, {json.dumps(subject)});
                    subjInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}

                // 4. Fill Body
                const bodyBox = document.querySelector('div[aria-label*="Message Body"], div[aria-label*="Nội dung thư"], div[role="textbox"]');
                if (bodyBox) {{
                    bodyBox.focus();
                    document.execCommand('insertText', false, {json.dumps(body)});
                    bodyBox.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}

                if ({json.dumps(send_now)}) {{
                    setTimeout(() => {{
                        const sendBtn = document.querySelector('div[role="button"][data-tooltip*="Send"], div[role="button"][data-tooltip*="Gửi"], .T-I.J-J5-Ji.aoO.v7.T-I-atl.L3');
                        if (sendBtn) {{
                            sendBtn.click();
                            resolve({{ ok: true, action: 'sent' }});
                        }} else {{
                            resolve({{ ok: false, error: 'Send button not found' }});
                        }}
                    }}, 500);
                }} else {{
                    resolve({{ ok: true, action: 'draft_created' }});
                }}
            }}, 600);
        }});
    }})()
    """
    res = eval_js(tab_id, script, bridge_url=bridge_url)
    if isinstance(res, dict) and res.get("ok"):
        return res
    err = res.get("error", "Unknown error composing Gmail") if isinstance(res, dict) else str(res)
    raise RuntimeError(f"Gmail compose failed: {err}")

