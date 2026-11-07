---
name: work-tracker
description: >-
  Manages daily work planning, in-day task checkpoints, blocker tracking, end-of-day standup reporting,
  and next-day rollover. Operates on local PROGRESS.md and integrates with Teams and Outlook action items.
  Trigger when the user asks to plan the day, view work progress, update task status, wrap up, draft daily reports,
  or prepare tomorrow's plan ("lên plan hôm nay", "tiến độ thế nào", "cập nhật task", "tổng kết ngày", "kế hoạch mai").
---

# Work Tracker Skill

Unified daily management protocol for engineering tasks, in-day checkpoints, blocker mitigation, end-of-day reporting, and next-day rollover.

## Core Responsibilities

1. **Morning Planning (Start-of-Day)**:
   - Read pending and rolled-over tasks from `PROGRESS.md`.
   - Inspect unread mentions and action items using `skills/chat/chat_tool.py pending` (Teams/Zalo) and `skills/mail/mail_tool.py pending` (Outlook).
   - Propose an ordered list of 3–5 focus tasks with explicit dependencies.
2. **In-Day Progress & Checkpoints**:
   - Track state: `[ ]` Pending, `[/]` In Progress, `[x]` Done, `[!]` Blocked.
   - Record verifiable evidence (commit hashes, test pass counts, PR links) upon completion.
   - Surface blockers immediately with the required contact person or access request.
3. **End-of-Day Wrap-Up & Reporting**:
   - Synthesize outcomes into 4 structured sections: Done, In Progress, Blockers, Tomorrow.
   - Format ready for posting to Microsoft Teams, Slack, or Email.
4. **Next-Day Rollover**:
   - Automatically carry forward unfinished tasks and prepare next-day priorities without manual re-typing.

---

## Tool Reference

The CLI utility lives at `skills/work-tracker/tracker.py`:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
TRACKER="python3 $REPO_ROOT/skills/work-tracker/tracker.py"

# 1. Initialize or view today's plan
$TRACKER plan

# 2. Add a priority task
$TRACKER add "Verify SAC auth flow with Playwright smoke tests"

# 3. Update task status (by 1-based index or search keyword)
# In Progress:
$TRACKER update 1 --status inprogress
# Done with evidence:
$TRACKER update 1 --status done --note "Passed 12/12 test cases, commit 3a4f8b"
# Blocked with reason:
$TRACKER update 2 --status blocked --note "Waiting on STG DB credentials from @Dat"

# 4. Log external blockers or dependencies
$TRACKER blocker "STG environment deployment delayed until 14:00"

# 5. Log next-day intentions
$TRACKER tomorrow "Review PR #204 from member"

# 6. Generate end-of-day digest / standup report
$TRACKER report

# 7. Rollover unfinished tasks to the next day
$TRACKER rollover
```

---

## Reporting Style

- **No emojis**: Clean markdown headers, lists, and tables.
- **Evidence first**: Never claim a task is "Done" without test counts, commit hashes, or reviewer approval.
- **State uncertainty plainly**: If an item is waiting on an external dependency, state who and what is needed.
