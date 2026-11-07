"""Unit tests for skills/work-tracker/tracker.py."""

import sys
import tempfile
import unittest
from pathlib import Path

TRACKER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TRACKER_DIR))
import tracker  # noqa: E402


class WorkTrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file_path = Path(self.tmp.name) / "PROGRESS.md"
        self.tracker = tracker.DailyWorkTracker(file_path=self.file_path)

    def test_ensure_today_section_creates_structure(self):
        content, created = self.tracker.ensure_today_section("2026-11-06")
        self.assertTrue(created)
        self.assertIn("## Date: 2026-11-06", content)
        self.assertIn("### Priorities", content)
        self.assertIn("### Blockers & Dependencies", content)
        self.assertIn("### Communications & Incoming Items", content)
        self.assertIn("### Tomorrow", content)

    def test_add_and_update_task(self):
        self.tracker.add_task("Implement login test", date_str="2026-11-06")
        self.tracker.add_task("Review PR #12", date_str="2026-11-06")

        day_data = self.tracker.parse_day("2026-11-06")
        self.assertEqual(len(day_data["priorities"]), 2)
        self.assertTrue(day_data["priorities"][0].startswith("[ ]"))

        # Update first task to inprogress
        res = self.tracker.update_task("1", "inprogress", date_str="2026-11-06")
        self.assertIn("inprogress", res)
        day_data = self.tracker.parse_day("2026-11-06")
        self.assertTrue(day_data["priorities"][0].startswith("[/]"))

        # Update task by keyword to done with note
        res = self.tracker.update_task("Review PR", "done", note="LGTM approved", date_str="2026-11-06")
        self.assertIn("done", res)
        day_data = self.tracker.parse_day("2026-11-06")
        self.assertTrue(day_data["priorities"][1].startswith("[x]"))
        self.assertIn("LGTM approved", day_data["priorities"][1])

    def test_blocker_and_tomorrow(self):
        self.tracker.add_entry("Blockers & Dependencies", "STG down for maintenance", date_str="2026-11-06")
        self.tracker.add_entry("Tomorrow", "Run regression suite", date_str="2026-11-06")

        day_data = self.tracker.parse_day("2026-11-06")
        self.assertEqual(day_data["blockers"], ["STG down for maintenance"])
        self.assertEqual(day_data["tomorrow"], ["Run regression suite"])

    def test_format_report(self):
        self.tracker.add_task("Task 1", date_str="2026-11-06")
        self.tracker.add_task("Task 2", date_str="2026-11-06")
        self.tracker.update_task("1", "done", note="commit abc", date_str="2026-11-06")
        self.tracker.update_task("2", "blocked", note="need creds", date_str="2026-11-06")
        self.tracker.add_entry("Tomorrow", "Task 3", date_str="2026-11-06")

        report = self.tracker.format_report("2026-11-06")
        self.assertIn("## 1. Đã hoàn thành (Done)", report)
        self.assertIn("Task 1 (commit abc)", report)
        self.assertIn("## 3. Vướng mắc & Phụ thuộc", report)
        self.assertIn("Task 2 (need creds)", report)
        self.assertIn("## 4. Kế hoạch ngày mai", report)
        self.assertIn("Task 3", report)

    def test_rollover_carries_forward_unfinished_tasks(self):
        self.tracker.add_task("Completed Task", date_str="2026-11-06")
        self.tracker.add_task("Unfinished Task", date_str="2026-11-06")
        self.tracker.update_task("Completed", "done", date_str="2026-11-06")
        self.tracker.add_entry("Tomorrow", "Planned for tomorrow", date_str="2026-11-06")

        res = self.tracker.rollover(from_date="2026-11-06", to_date="2026-11-07")
        self.assertIn("Successfully rolled over 2 task(s)", res)

        next_day = self.tracker.parse_day("2026-11-07")
        self.assertEqual(len(next_day["priorities"]), 2)
        tasks = [p.replace("[ ] ", "") for p in next_day["priorities"]]
        self.assertIn("Unfinished Task", tasks)
        self.assertIn("Planned for tomorrow", tasks)


if __name__ == "__main__":
    unittest.main()
