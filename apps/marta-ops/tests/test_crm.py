"""CRM relationships, old-data preservation, and atomic pipeline moves."""

from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import MartaOpsError
from service import handle_action


class MartaOpsCRMTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, action, **body):
        return handle_action(self.root, {"action": action, **body})[1]

    def work(self, title, phase="lead", **fields):
        return self.call("create_collaboration", collaboration={"title": title, "phase": phase, **fields})["collaboration"]

    def contact(self, **fields):
        return self.call("create_contact", contact={"name": "Anna Rossi", **fields})["contact"]

    def test_old_state_is_read_without_loss_or_implicit_write(self):
        original = {"schema_version": "1", "collaborations": [{"id": "old", "title": "Esistente", "phase": "production", "notes": "Brief", "deliverables": [{"id": "reel", "title": "Reel"}]}], "ideas": [{"id": "idea", "title": "Sci"}]}
        path = self.root / "state.json"
        path.write_text(json.dumps(original))
        state = self.call("bootstrap")["state"]
        self.assertEqual(state["collaborations"][0]["deliverables"], original["collaborations"][0]["deliverables"])
        self.assertEqual(state["ideas"], original["ideas"])
        self.assertEqual(state["contacts"], [])
        self.assertEqual(json.loads(path.read_text()), original)
        self.contact()
        saved = self.call("bootstrap")["state"]
        self.assertEqual(saved["collaborations"][0]["notes"], "Brief")
        self.assertEqual(saved["ideas"], original["ideas"])

    def test_contact_link_and_mail_recipient(self):
        contact = self.contact(company="Outdoor", email="anna@example.test", tags=["Brand", "Brand", "Sport"])
        work = self.work("Campagna", contact_id=contact["id"])
        request = self.call("create_mail_draft", id=work["id"])["dependency_backend_requests"][0]
        self.assertEqual(request["body"]["to"], [{"email": "anna@example.test"}])
        self.assertEqual(contact["tags"], ["Brand", "Sport"])
        self.call("update_contact", id=contact["id"], changes={"archived": True})
        self.assertEqual(self.call("bootstrap")["state"]["collaborations"][0]["contact_id"], contact["id"])

    def test_invalid_contact_reference_does_not_create_work(self):
        with self.assertRaises(MartaOpsError):
            self.work("Invalid", contact_id="missing")
        self.assertEqual(self.call("bootstrap")["state"]["collaborations"], [])

    def test_contact_validation_is_atomic(self):
        contact = self.contact(email="anna@example.test")
        for changes in [{"email": "invalid"}, {"tags": "Brand"}, {"archived": "false"}]:
            with self.assertRaises(MartaOpsError):
                self.call("update_contact", id=contact["id"], changes=changes)
        saved = self.call("bootstrap")["state"]["contacts"][0]
        self.assertEqual(saved["email"], "anna@example.test")
        self.assertFalse(saved["archived"])

    def test_move_preserves_hidden_cards_and_contiguous_order(self):
        a, hidden, b = self.work("A"), self.work("Hidden"), self.work("B")
        self.call("move_collaboration", id=b["id"], phase="lead", before_id=a["id"], expected_phase="lead")
        state = self.call("bootstrap")["state"]
        column = sorted(state["collaborations"], key=lambda w: w["pipeline_order"])
        self.assertEqual([w["id"] for w in column], [b["id"], a["id"], hidden["id"]])
        self.assertEqual([w["pipeline_order"] for w in column], [0, 1, 2])
        self.call("move_collaboration", id=a["id"], phase="production", before_id="", expected_phase="lead")
        state = self.call("bootstrap")["state"]
        self.assertEqual(next(w for w in state["collaborations"] if w["id"] == a["id"])["phase"], "production")
        self.assertEqual(len(state["activity"]), 4)

    def test_stale_move_and_wrong_anchor_leave_state_unchanged(self):
        a = self.work("A")
        other = self.work("Other", "proposal")
        before = self.call("bootstrap")["state"]
        for args in [{"phase": "production", "expected_phase": "proposal"}, {"phase": "lead", "before_id": other["id"]}]:
            with self.assertRaises(MartaOpsError):
                self.call("move_collaboration", id=a["id"], **args)
        self.assertEqual(self.call("bootstrap")["state"], before)

    def test_task_round_trip_completion_and_reopening(self):
        contact = self.contact()
        work = self.work("Work", contact_id=contact["id"])
        task = self.call("create_task", task={"title": "Richiamare Anna", "kind": "call", "due_date": "2026-10-01", "contact_id": contact["id"], "collaboration_id": work["id"]})["task"]
        done = self.call("update_task", id=task["id"], changes={"done": True})["task"]
        self.assertTrue(done["completed_at"])
        reopened = self.call("update_task", id=task["id"], changes={"done": False})["task"]
        self.assertEqual(reopened["completed_at"], "")
        self.assertEqual(reopened["contact_id"], contact["id"])

    def test_task_rejects_unknown_links_and_invalid_dates(self):
        for fields in [{"contact_id": "missing"}, {"collaboration_id": "missing"}, {"due_date": "2026-02-30"}, {"done": "yes"}]:
            with self.assertRaises(MartaOpsError):
                self.call("create_task", task={"title": "Follow-up", **fields})
        self.assertEqual(self.call("bootstrap")["state"]["tasks"], [])

    def test_notes_are_linked_and_preserve_text_as_plain_data(self):
        contact = self.contact()
        note = self.call("add_note", contact_id=contact["id"], text="<script>test</script>")["activity"]
        self.assertEqual(note["text"], "<script>test</script>")
        self.assertEqual(note["contact_id"], contact["id"])
        with self.assertRaises(MartaOpsError):
            self.call("add_note", text="Orphan")

    def test_manual_phase_change_appends_to_destination(self):
        first = self.work("First", "production")
        moved = self.work("Moved")
        self.call("update_collaboration", id=moved["id"], changes={"phase": "production"})
        column = sorted(self.call("bootstrap")["state"]["collaborations"], key=lambda w: w["pipeline_order"])
        self.assertEqual([w["id"] for w in column], [first["id"], moved["id"]])

    def test_new_work_appends_after_sparse_old_order(self):
        original = {"schema_version": "1", "collaborations": [{"id": "a", "title": "A", "phase": "lead"}, {"id": "other", "title": "Other", "phase": "production"}, {"id": "b", "title": "B", "phase": "lead"}], "ideas": []}
        (self.root / "state.json").write_text(json.dumps(original))
        self.work("New")
        items = sorted((w for w in self.call("bootstrap")["state"]["collaborations"] if w["phase"] == "lead"), key=lambda w: w["pipeline_order"])
        self.assertEqual([w["title"] for w in items], ["A", "B", "New"])
        self.assertEqual(len(set(w["pipeline_order"] for w in items)), 3)


if __name__ == "__main__":
    unittest.main()
