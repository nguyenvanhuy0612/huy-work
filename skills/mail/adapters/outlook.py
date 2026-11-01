"""Outlook Web adapter for email harvesting and dispatch."""

import json
from typing import Any, Dict, List, Optional

from skills.common.bridge import DEFAULT_BRIDGE_URL, eval_js, find_tab


def find_outlook_tab(bridge_url: str = DEFAULT_BRIDGE_URL) -> Optional[Dict[str, Any]]:
    """Discovers active Outlook Web tabs (Office 365 or Live/Hotmail)."""
    return find_tab(
        url_patterns=["outlook.office.com", "outlook.office365.com", "outlook.live.com"],
        title_patterns=["Outlook"],
        bridge_url=bridge_url,
    )


def harvest_outlook_emails(tab_id: int, max_items: int = 50, bridge_url: str = DEFAULT_BRIDGE_URL) -> List[Dict[str, Any]]:
    """Harvests email metadata from the active Outlook Web list view."""
    script = r"""
    (() => {
        const results = [];
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
            } catch (e) {}
        }
        return results;
    })()
    """
    res = eval_js(tab_id, script, bridge_url=bridge_url)
    items = res if isinstance(res, list) else []
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
    res = eval_js(tab_id, script, bridge_url=bridge_url)
    return res if isinstance(res, dict) else {"result": res}


def compose_outlook_email(
    tab_id: int,
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    send_now: bool = False,
    bridge_url: str = DEFAULT_BRIDGE_URL,
) -> Dict[str, Any]:
    """Opens compose pane in Outlook Web, populates fields, and optionally dispatches send."""
    script = f"""
    (() => {{
        // 1. Click New Mail button if not already composing
        let newBtn = document.querySelector('button[aria-label*="New mail"], button[aria-label*="Thư mới"], button[id*="newMail"]');
        if (newBtn) newBtn.click();

        return new Promise((resolve) => {{
            setTimeout(() => {{
                // Find input fields
                const toInput = document.querySelector('div[aria-label*="To"] input, input[aria-label*="To"], div[data-testid*="recipient-to"] input');
                if (toInput) {{
                    toInput.focus();
                    document.execCommand('insertText', false, {json.dumps(to)});
                    toInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}

                const ccVal = {json.dumps(cc)};
                if (ccVal) {{
                    const ccBtn = document.querySelector('button[aria-label*="Cc"], button[aria-label*="Sao chép"]');
                    if (ccBtn) ccBtn.click();
                    const ccInput = document.querySelector('div[aria-label*="Cc"] input, input[aria-label*="Cc"]');
                    if (ccInput) {{
                        ccInput.focus();
                        document.execCommand('insertText', false, ccVal);
                        ccInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    }}
                }}

                const subjectInput = document.querySelector('input[aria-label*="Subject"], input[placeholder*="Add a subject"], input[placeholder*="Thêm chủ đề"]');
                if (subjectInput) {{
                    subjectInput.focus();
                    document.execCommand('insertText', false, {json.dumps(subject)});
                    subjectInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}

                const bodyBox = document.querySelector('div[aria-label*="Message body"], div[role="textbox"]');
                if (bodyBox) {{
                    bodyBox.focus();
                    document.execCommand('insertText', false, {json.dumps(body)});
                    bodyBox.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}

                if ({json.dumps(send_now)}) {{
                    setTimeout(() => {{
                        const sendBtn = document.querySelector('button[aria-label*="Send"], button[title*="Send"], button[aria-label*="Gửi"]');
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
    err = res.get("error", "Unknown error composing Outlook mail") if isinstance(res, dict) else str(res)
    raise RuntimeError(f"Outlook compose failed: {err}")

