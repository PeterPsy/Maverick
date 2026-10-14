"""Bounded, read-only operational sidebar counts."""

from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import MartaOpsError
from service import app_events_for_action, handle_action


class SidebarSummaryTest(unittest.TestCase):
    def test_counts_include_unpaid_closed_work_and_exclude_published_deliveries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = {
                "collaborations": [
                    {"phase": "production", "payment_status": "paid", "deliverables": [
                        {"status": "approval", "due_date": "2026-09-30"},
                        {"status": "published", "due_date": "2026-09-29"},
                        {"status": "planned", "due_date": "2026-10-01"},
                        {"status": "planned", "due_date": ""},
                    ]},
                    {"phase": "completed", "payment_status": "overdue"},
                    {"phase": "lost", "payment_status": "not_due"},
                    {"phase": "lead", "payment_status": "invoiced"},
                    {"phase": "proposal", "payment_status": "to_invoice"},
                ],
                "tasks": [{"done": False}, {"done": True}],
            }
            path = root / "state.json"
            path.write_text(json.dumps(original))
            before = path.read_bytes()
            status, payload = handle_action(root, {"action": "sidebar_summary", "today": "2026-10-01"})
            self.assertEqual(status, 200)
            self.assertEqual(payload, {"summary": {
                "overdue_deliveries": 1, "approvals": 1,
                "open_tasks": 1, "receivables": 2, "overdue_payments": 1,
            }})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(app_events_for_action("sidebar_summary"), [])

    def test_local_date_is_required_and_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in [None, "", "2026-02-30", "20261001", 42]:
                with self.subTest(value=value), self.assertRaises(MartaOpsError):
                    handle_action(Path(directory), {"action": "sidebar_summary", "today": value})


if __name__ == "__main__":
    unittest.main()
