"""Regression coverage for stopped dispatches, definitive failures and results."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from scheduled_service import handle_scheduled
from scheduled_store import connection
from scheduled_tick import tick


class ScheduledRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = temp.name

    def call(self, action, **body):
        return handle_scheduled({"data_root": self.root, "surface": "backend", "user_id": "alice",
                                 "body": {"action": "scheduled." + action, **body}})

    def create(self, *, count=1):
        nodes = [{"id": str(index), "title": str(index), "instructions": "Complete this block",
                  "skill_ids": [], "position": {"x": 0, "y": 0}} for index in range(count)]
        return self.call("create", title="Recovery", graph={"nodes": nodes, "edges": []})["chat"]

    def callback(self, request, status="submitted", *, session_id="work", turn_id="turn"):
        return handle_scheduled({"data_root": self.root, "surface": "runtime_request_callback", "body": {
            "action": "scheduled.started", "dispatch_id": request["request_id"], "request_id": request["request_id"],
            "runtime_request_status": status, "runtime_session_id": session_id, "turn_id": turn_id,
            "error": "Transient launch failure" if status == "failed" else ""}})

    def test_stopped_launches_are_not_replayed_after_the_recovery_timeout(self):
        for action in ("pause", "cancel", "delete"):
            with self.subTest(action=action):
                chat = self.create()
                request = self.call("run", chat_id=chat["id"])["runtime_session_requests"][0]
                self.call(action, chat_id=chat["id"])
                with connection(self.root, write=True) as db:
                    # Also fence an orphan persisted before the stop-fence fix.
                    db.execute("UPDATE scheduled_requests SET status='launching',updated_at=0 WHERE id=?", (request["request_id"],))
                recovered = tick(self.root, {"runtime_request_states": []})
                self.assertNotIn(request["request_id"], [item["request_id"] for item in recovered.get("runtime_session_requests", [])])

    def test_stopped_unbound_launches_release_slots_and_fence_late_callbacks(self):
        chat = self.create(count=4)
        request = self.call("run", chat_id=chat["id"])["runtime_session_requests"][0]
        self.call("pause", chat_id=chat["id"])
        self.call("resume", chat_id=chat["id"])
        late = self.callback(request)
        self.assertEqual(late["runtime_turn_interrupt_requests"], [{"turn_id": "turn", "reason": "Scheduled task stopped"}])
        step = self.call("read", chat_id=chat["id"])["chat"]["run"]["steps"][0]
        self.assertEqual(step["status"], "cancelled")
        other = self.create(count=4)
        self.assertEqual(len(self.call("run", chat_id=other["id"])["runtime_session_requests"]), 4)

    def test_deleted_management_launch_is_not_replayed_or_rebound(self):
        created = self.call("create", title="Deleted", graph={"nodes": [{"id": "a", "title": "A", "instructions": "Do A"}], "edges": []})
        request = created["runtime_session_requests"][0]
        self.call("delete", chat_id=created["chat"]["id"])
        with connection(self.root, write=True) as db:
            db.execute("UPDATE scheduled_requests SET updated_at=0 WHERE id=?", (request["request_id"],))
        self.assertFalse(tick(self.root, {"runtime_request_states": []}).get("runtime_session_requests"))
        late = self.callback(request)
        self.assertTrue(late["runtime_turn_interrupt_requests"])
        with connection(self.root) as db:
            self.assertEqual(db.execute("SELECT chat_session_id FROM scheduled_chats WHERE id=?", (created["chat"]["id"],)).fetchone()[0], "")

    def test_definitive_launch_failure_retries_with_a_fresh_key(self):
        chat = self.create()
        first = self.call("run", chat_id=chat["id"])
        request = first["runtime_session_requests"][0]
        self.callback(request, "failed", session_id="reserved-session", turn_id="")
        retry = self.call("retry", chat_id=chat["id"], run_id=first["chat"]["run"]["id"], node_id="0")
        self.assertNotEqual(retry["runtime_session_requests"][0]["idempotency_key"], request["idempotency_key"])
        self.assertTrue(self.callback(request)["ignored"])

    def test_ambiguous_stopped_launch_keeps_its_key_on_explicit_retry(self):
        chat = self.create()
        first = self.call("run", chat_id=chat["id"])
        request = first["runtime_session_requests"][0]
        self.call("pause", chat_id=chat["id"])
        self.call("resume", chat_id=chat["id"])
        retry = self.call("retry", chat_id=chat["id"], run_id=first["chat"]["run"]["id"], node_id="0")
        self.assertEqual(retry["runtime_session_requests"], [request])

    def test_terminal_state_waits_for_the_result_before_confirming_and_handoff(self):
        chat = self.create(count=2)
        graph = chat["graph"]
        graph["edges"] = [{"id": "0-1", "source": "0", "target": "1"}]
        self.call("update", chat_id=chat["id"], expected_revision=1, graph=graph)
        first = self.call("run", chat_id=chat["id"])
        request = first["runtime_session_requests"][0]
        state = {"request_id": request["request_id"], "session_id": "work", "turn_id": "turn", "status": "completed"}
        tick(self.root, {"runtime_request_states": [state]})
        waiting = self.call("read", chat_id=chat["id"])["chat"]["run"]["steps"][0]
        self.assertEqual(waiting["status"], "running")
        with self.assertRaises(ValueError):
            self.call("continue", chat_id=chat["id"], run_id=first["chat"]["run"]["id"], node_ids=["0"])
        tick(self.root, {"runtime_request_states": [{**state, "output_text": "Recovered result"}]})
        continued = self.call("continue", chat_id=chat["id"], run_id=first["chat"]["run"]["id"], node_ids=["0"])
        prompt = json.loads(continued["runtime_session_requests"][0]["input_text"].split("\n", 1)[1])
        self.assertEqual(prompt["predecessor_outputs"][0]["output"], "Recovered result")

    def test_authoritatively_empty_result_can_still_reach_a_checkpoint(self):
        chat = self.create()
        request = self.call("run", chat_id=chat["id"])["runtime_session_requests"][0]
        tick(self.root, {"runtime_request_states": [{"request_id": request["request_id"], "session_id": "work",
            "turn_id": "turn", "status": "completed", "output_text": ""}]})
        self.assertEqual(self.call("read", chat_id=chat["id"])["chat"]["run"]["steps"][0]["status"], "checkpoint")

    def test_recovery_without_an_output_does_not_consume_the_later_result_event(self):
        chat = self.create()
        request = self.call("run", chat_id=chat["id"])["runtime_session_requests"][0]
        event = {"action": "runtime.turn.completed", "turn_status": "completed", "runtime_request_id": request["request_id"],
                 "runtime_session_id": "work", "turn_id": "turn"}
        tick(self.root, {"runtime_request_states": [], "recent_terminal_exchanges": [event]})
        self.assertEqual(self.call("read", chat_id=chat["id"])["chat"]["run"]["steps"][0]["status"], "running")
        handle_scheduled({"data_root": self.root, "surface": "runtime_event", "body": {**event, "output_text": "Late result"}})
        step = self.call("read", chat_id=chat["id"])["chat"]["run"]["steps"][0]
        self.assertEqual((step["status"], step["output"]), ("checkpoint", "Late result"))

    def test_recovery_retries_a_late_interrupt_after_resume_until_core_stops_it(self):
        chat = self.create()
        request = self.call("run", chat_id=chat["id"])["runtime_session_requests"][0]
        self.call("pause", chat_id=chat["id"])
        self.call("resume", chat_id=chat["id"])
        self.callback(request)
        state = {"request_id": request["request_id"], "session_id": "work", "turn_id": "turn", "status": "running"}
        recovered = tick(self.root, {"runtime_request_states": [state]})
        self.assertEqual(len(recovered["runtime_turn_interrupt_requests"]), 1)
        stopped = tick(self.root, {"runtime_request_states": [{**state, "status": "cancelled"}]})
        self.assertFalse(stopped.get("runtime_turn_interrupt_requests"))
        self.assertFalse(stopped.get("_scheduled_changed"))


if __name__ == "__main__":
    unittest.main()
