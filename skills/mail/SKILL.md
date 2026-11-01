---
name: mail
description: >-
  Inspects, searches, synchronizes, summarizes, creates drafts, and dispatches emails across Outlook Web
  and Gmail. Supports multi-account Gmail inspection. Uses local SQLite storage with FTS5. Trigger when
  the user asks about emails, unread inbox, announcements, or asks to draft/send emails.
---

# Mail Skill (Outlook Web & Gmail)

Unified tool for email ingestion, full-text searching, digest maintenance, draft creation, and controlled email dispatch across Outlook Web and Gmail.

## Core Responsibilities

1. **Email Querying**: Search emails, announcements, and threads using full-text search (FTS5) across Outlook and Gmail in a single command.
2. **Periodic Synchronization**: Pull new messages from active Outlook or Gmail browser tabs via `browserctl` into `skills/mail/mail.db`.
3. **Multi-Account Gmail Management**: Inspect open Gmail tabs and verify account email (`window.GLOBALS`, avatar tooltip) before synchronizing or sending to prevent cross-account leakage.
4. **Draft & Send (Write)**: Create drafts or send emails with mandatory human-in-the-loop preview.

---

## Tool Reference

The CLI utility lives at `skills/mail/mail_tool.py`:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
MAIL_TOOL="$REPO_ROOT/skills/mail/mail_tool.py"

# 1. Detect open email accounts and active tabs
python3 "$MAIL_TOOL" accounts

# 2. View recent emails across platforms or filtered
python3 "$MAIL_TOOL" list --limit 30
python3 "$MAIL_TOOL" --app gmail --account "nguyenvanhuy0612@gmail.com" list --unread
python3 "$MAIL_TOOL" --app outlook list --unread

# 3. Read specific email or thread content
python3 "$MAIL_TOOL" read --id "<email_id_or_thread_id>"

# 4. Search emails using FTS5 (across all or filtered by app/account)
python3 "$MAIL_TOOL" search "<query>"
python3 "$MAIL_TOOL" --app gmail search "<query>"

# 5. View pending unreviewed emails
python3 "$MAIL_TOOL" pending

# 6. Synchronize from browser tabs
# Outlook:
python3 "$MAIL_TOOL" --app outlook sync
# Gmail (targets specific account):
python3 "$MAIL_TOOL" --app gmail --account "nguyenvanhuy0612@gmail.com" sync

# 7. Acknowledge emails after review
python3 "$MAIL_TOOL" ack --all

# 8. Create Draft (Safe default, opens compose window and populates fields)
python3 "$MAIL_TOOL" --app gmail --account "nguyenvanhuy0612@gmail.com" draft \
  --to "lead@example.com" --subject "QA Weekly Summary" --body "Please find the report below..."

# 9. Send Email (Outbound action preview by default; requires --confirm)
# Preview first:
python3 "$MAIL_TOOL" --app gmail --account "nguyenvanhuy0612@gmail.com" send \
  --to "lead@example.com" --subject "Urgent Notice" --body "..."
# Dispatch upon explicit approval:
python3 "$MAIL_TOOL" --app gmail --account "nguyenvanhuy0612@gmail.com" send \
  --to "lead@example.com" --subject "Urgent Notice" --body "..." --confirm
```

---

## Safety Guardrail

Before running `send --confirm`:
1. Execute the command without `--confirm` to generate the `[OUTBOUND ACTION PREVIEW]`.
2. Present the exact recipient, account, subject, and body content to the user in chat.
3. Wait for explicit user go-ahead before executing the command with `--confirm`.

