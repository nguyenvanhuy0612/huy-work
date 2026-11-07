#!/usr/bin/env python3
"""Daily Work & Progress Tracker for corporate engineering workflows.

Manages daily priorities, in-day task checkpoints, blocker tracking,
daily standup/wrap-up reports, and next-day rollover in a structured PROGRESS.md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

STATUS_SYMBOLS = {
    "pending": "[ ]",
    "inprogress": "[/]",
    "done": "[x]",
    "blocked": "[!]",
}

REV_STATUS = {
    "[ ]": "pending",
    "[/]": "inprogress",
    "[x]": "done",
    "[!]": "blocked",
}


def get_default_progress_file() -> Path:
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / "PROGRESS.md"


class DailyWorkTracker:
    def __init__(self, file_path: Optional[Path] = None):
        self.file_path = file_path or get_default_progress_file()

    def load_content(self) -> str:
        if self.file_path.exists():
            return self.file_path.read_text(encoding="utf-8")
        return ""

    def save_content(self, content: str) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(content, encoding="utf-8")

    def ensure_today_section(self, today_str: Optional[str] = None) -> Tuple[str, bool]:
        """Ensures section for given date exists; returns (content, newly_created)."""
        content = self.load_content()
        date_str = today_str or dt.date.today().isoformat()
        header = f"## Date: {date_str}"
        if header in content:
            return content, False

        new_section = (
            f"\n{header}\n\n"
            f"### Priorities\n\n"
            f"### Blockers & Dependencies\n\n"
            f"### Communications & Incoming Items\n\n"
            f"### Tomorrow\n"
        )
        if not content.strip():
            content = f"# Daily Work Tracker\nLast updated: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n" + new_section
        else:
            lines = content.splitlines()
            top = []
            idx = 0
            while idx < len(lines) and not lines[idx].startswith("## Date:"):
                top.append(lines[idx])
                idx += 1
            rest = lines[idx:]
            top_str = "\n".join(top).strip()
            rest_str = "\n".join(rest).strip()
            content = f"{top_str}\n{new_section}\n{rest_str}".strip() + "\n"

        self.save_content(content)
        return content, True

    def add_task(self, text: str, date_str: Optional[str] = None) -> str:
        self.ensure_today_section(date_str)
        content = self.load_content()
        date_tag = f"## Date: {date_str or dt.date.today().isoformat()}"

        pattern = re.compile(rf"({re.escape(date_tag)}.*?### Priorities\n)(.*?)(### Blockers|\Z)", re.S)
        match = pattern.search(content)
        if not match:
            return "Error: Could not locate Priorities section."

        p_header, existing_tasks, next_part = match.groups()
        new_line = f"- [ ] {text.strip()}\n"
        updated_tasks = existing_tasks.rstrip() + ("\n" if existing_tasks.strip() else "") + new_line
        new_block = f"{p_header}{updated_tasks}\n{next_part}"
        content = content[:match.start()] + new_block + content[match.end():]
        self.save_content(content)
        return f"Added task: {text.strip()}"

    def update_task(self, identifier: str, status: str, note: Optional[str] = None, date_str: Optional[str] = None) -> str:
        self.ensure_today_section(date_str)
        content = self.load_content()
        date_tag = f"## Date: {date_str or dt.date.today().isoformat()}"

        status_key = status.lower().strip()
        if status_key not in STATUS_SYMBOLS:
            return f"Invalid status: {status}. Allowed: {list(STATUS_SYMBOLS.keys())}"
        symbol = STATUS_SYMBOLS[status_key]

        pattern = re.compile(rf"({re.escape(date_tag)}.*?### Priorities\n)(.*?)(### Blockers|\Z)", re.S)
        match = pattern.search(content)
        if not match:
            return "Error: Could not locate Priorities section."

        p_header, task_lines, next_part = match.groups()
        lines = task_lines.splitlines()
        found = False
        target_idx = -1

        if identifier.isdigit():
            idx = int(identifier) - 1
            if 0 <= idx < len(lines):
                target_idx = idx

        for i, line in enumerate(lines):
            if not line.strip().startswith("- ["):
                continue
            if target_idx == i or (target_idx == -1 and identifier.lower() in line.lower()):
                m = re.match(r"^-\s*\[([ x/!])\]\s*(.*?)(?:\s*\((.*?)\))?$", line.strip())
                if m:
                    base_text = m.group(2).strip()
                    existing_note = m.group(3)
                    final_note = note if note is not None else existing_note
                    note_str = f" ({final_note})" if final_note else ""
                    lines[i] = f"- {symbol} {base_text}{note_str}"
                    found = True
                    break

        if not found:
            return f"Task matching '{identifier}' not found."

        updated_tasks = "\n".join(lines) + "\n"
        new_block = f"{p_header}{updated_tasks}\n{next_part}"
        content = content[:match.start()] + new_block + content[match.end():]
        self.save_content(content)
        return f"Updated task to {status_key} ({symbol})"

    def add_entry(self, section: str, text: str, date_str: Optional[str] = None) -> str:
        self.ensure_today_section(date_str)
        content = self.load_content()
        date_tag = f"## Date: {date_str or dt.date.today().isoformat()}"
        sec_header = f"### {section}"

        pattern = re.compile(rf"({re.escape(date_tag)}.*?{re.escape(sec_header)}\n)(.*?)(###|\Z)", re.S)
        match = pattern.search(content)
        if not match:
            return f"Error: Could not locate {section} section."

        header_part, existing_entries, next_part = match.groups()
        new_line = f"- {text.strip()}\n"
        updated = existing_entries.rstrip() + ("\n" if existing_entries.strip() else "") + new_line
        new_block = f"{header_part}{updated}\n{next_part}"
        content = content[:match.start()] + new_block + content[match.end():]
        self.save_content(content)
        return f"Added entry to {section}: {text.strip()}"

    def parse_day(self, date_str: Optional[str] = None) -> Dict[str, List[str]]:
        content = self.load_content()
        date_tag = f"## Date: {date_str or dt.date.today().isoformat()}"
        if date_tag not in content:
            return {}

        pattern = re.compile(rf"{re.escape(date_tag)}\n(.*?)(?=\n## Date:|\Z)", re.S)
        match = pattern.search(content)
        if not match:
            return {}

        block = match.group(1)
        sections: Dict[str, List[str]] = {"priorities": [], "blockers": [], "communications": [], "tomorrow": []}
        curr = None
        for line in block.splitlines():
            line_str = line.strip()
            if line_str.startswith("### Priorities"):
                curr = "priorities"
            elif line_str.startswith("### Blockers"):
                curr = "blockers"
            elif line_str.startswith("### Communications"):
                curr = "communications"
            elif line_str.startswith("### Tomorrow"):
                curr = "tomorrow"
            elif line_str.startswith("- ") and curr:
                sections[curr].append(line_str[2:].strip())
        return sections

    def format_report(self, date_str: Optional[str] = None) -> str:
        target_date = date_str or dt.date.today().isoformat()
        day_data = self.parse_day(target_date)
        if not day_data:
            return f"No records found for date {target_date}."

        done_list = []
        inprogress_list = []
        blocked_list = []
        pending_list = []

        for p in day_data.get("priorities", []):
            if p.startswith("[x]"):
                done_list.append(p[3:].strip())
            elif p.startswith("[/]"):
                inprogress_list.append(p[3:].strip())
            elif p.startswith("[!]"):
                blocked_list.append(p[3:].strip())
            elif p.startswith("[ ]"):
                pending_list.append(p[3:].strip())
            else:
                pending_list.append(p)

        blockers = day_data.get("blockers", [])
        tomorrow = day_data.get("tomorrow", [])

        report_lines = [
            f"# Daily Report ({target_date})",
            "",
            "## 1. Đã hoàn thành (Done)",
        ]
        if done_list:
            for item in done_list:
                report_lines.append(f"- {item}")
        else:
            report_lines.append("- (Chưa có task hoàn thành trong ngày)")

        report_lines.extend(["", "## 2. Đang thực hiện & Chờ (In Progress & Pending)"])
        if inprogress_list or pending_list:
            for item in inprogress_list:
                report_lines.append(f"- [Đang làm] {item}")
            for item in pending_list:
                report_lines.append(f"- [Chưa bắt đầu] {item}")
        else:
            report_lines.append("- (Không còn task tồn)")

        report_lines.extend(["", "## 3. Vướng mắc & Phụ thuộc (Blockers & Dependencies)"])
        all_blockers = blocked_list + blockers
        if all_blockers:
            for item in all_blockers:
                report_lines.append(f"- {item}")
        else:
            report_lines.append("- Không có blocker nào.")

        report_lines.extend(["", "## 4. Kế hoạch ngày mai (Next-Day Plan)"])
        if tomorrow or inprogress_list:
            for item in inprogress_list:
                report_lines.append(f"- Tiếp tục: {item}")
            for item in tomorrow:
                report_lines.append(f"- {item}")
        else:
            report_lines.append("- Duy trì tiến độ và theo dõi backlog.")

        return "\n".join(report_lines)

    def rollover(self, from_date: Optional[str] = None, to_date: Optional[str] = None) -> str:
        from_str = from_date or dt.date.today().isoformat()
        to_str = to_date or (dt.date.today() + dt.timedelta(days=1)).isoformat()

        day_data = self.parse_day(from_str)
        if not day_data:
            return f"No day data found for {from_str} to rollover."

        rollover_tasks = []
        for p in day_data.get("priorities", []):
            if not p.startswith("[x]"):
                clean = re.sub(r"^\[[ /!]\]\s*", "", p)
                rollover_tasks.append(clean)
        for t in day_data.get("tomorrow", []):
            if t not in rollover_tasks:
                rollover_tasks.append(t)

        self.ensure_today_section(to_str)
        for task in rollover_tasks:
            self.add_task(task, date_str=to_str)

        return f"Successfully rolled over {len(rollover_tasks)} task(s) from {from_str} to {to_str}."


def main():
    parser = argparse.ArgumentParser(description="Daily Work Tracker CLI")
    parser.add_argument("--file", type=Path, help="Path to PROGRESS.md file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # plan / init
    p_plan = subparsers.add_parser("plan", help="Initialize or display today's plan")
    p_plan.add_argument("--date", help="Date in YYYY-MM-DD")

    # add task
    p_add = subparsers.add_parser("add", help="Add a priority task")
    p_add.add_argument("text", help="Task description")
    p_add.add_argument("--date", help="Date in YYYY-MM-DD")

    # update task
    p_up = subparsers.add_parser("update", help="Update task status")
    p_up.add_argument("id", help="Task number (1, 2) or keyword")
    p_up.add_argument("--status", choices=["pending", "inprogress", "done", "blocked"], required=True)
    p_up.add_argument("--note", help="Evidence, commit hash, or blocker reason")
    p_up.add_argument("--date", help="Date in YYYY-MM-DD")

    # blocker
    p_block = subparsers.add_parser("blocker", help="Add blocker or dependency")
    p_block.add_argument("text", help="Blocker description")
    p_block.add_argument("--date", help="Date in YYYY-MM-DD")

    # tomorrow
    p_tom = subparsers.add_parser("tomorrow", help="Add next-day item")
    p_tom.add_argument("text", help="Next-day plan item")
    p_tom.add_argument("--date", help="Date in YYYY-MM-DD")

    # report
    p_rep = subparsers.add_parser("report", help="Generate daily wrap-up report")
    p_rep.add_argument("--date", help="Date in YYYY-MM-DD")

    # rollover
    p_roll = subparsers.add_parser("rollover", help="Rollover unfinished tasks to next day")
    p_roll.add_argument("--from-date", help="Source date in YYYY-MM-DD")
    p_roll.add_argument("--to-date", help="Target date in YYYY-MM-DD")

    args = parser.parse_args()
    tracker = DailyWorkTracker(file_path=args.file)

    if args.command == "plan":
        tracker.ensure_today_section(args.date)
        content = tracker.load_content()
        target_date = args.date or dt.date.today().isoformat()
        pattern = re.compile(rf"(## Date: {re.escape(target_date)}\n.*?)((?=\n## Date:)|\Z)", re.S)
        m = pattern.search(content)
        print(m.group(1).strip() if m else f"No plan found for {target_date}")
    elif args.command == "add":
        print(tracker.add_task(args.text, date_str=args.date))
    elif args.command == "update":
        print(tracker.update_task(args.id, args.status, note=args.note, date_str=args.date))
    elif args.command == "blocker":
        print(tracker.add_entry("Blockers & Dependencies", args.text, date_str=args.date))
    elif args.command == "tomorrow":
        print(tracker.add_entry("Tomorrow", args.text, date_str=args.date))
    elif args.command == "report":
        print(tracker.format_report(date_str=args.date))
    elif args.command == "rollover":
        print(tracker.rollover(from_date=args.from_date, to_date=args.to_date))


if __name__ == "__main__":
    main()
