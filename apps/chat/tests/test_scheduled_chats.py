"""Scheduled-chat invariants: real transactions, runtime envelopes and recurrence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from scheduled_service import handle_scheduled, scheduled_references
from scheduled_store import connection
from scheduled_tick import tick
from scheduled_validation import next_due, validate_graph, validate_schedule
from scheduled_cleanup import cleanup
from scheduled_response import envelope
from core.shared.entrypoints import run_json_entrypoint
from core.apps.contracts import parse_app_contract_file

APP_ROOT = Path(__file__).resolve().parents[1]


def block(node_id):
    return {"id": node_id, "title": node_id, "instructions": "Execute " + node_id, "skill_ids": [], "position": {"x": 0, "y": 0}}


class ScheduledChatTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = temp.name
        self.graph = {"nodes": [block("a"), block("b"), block("join")],
                      "edges": [{"id": "a-join", "source": "a", "target": "join"}, {"id": "b-join", "source": "b", "target": "join"}]}

    def call(self, action, actor="alice", surface="backend", **body):
        return handle_scheduled({"data_root": self.root, "user_id": actor, "surface": surface,
                                 "body": {"action": "scheduled." + action, **body}})

    def create(self, **fields):
        return self.call("create", title="Morning brief", graph=self.graph,
                         schedule={"frequency": "manual", "timezone": "UTC"}, **fields)["chat"]

    def terminal(self, request, status="completed", output="Done"):
        body = {"runtime_request_id": request["request_id"], "turn_id": "turn-" + request["request_id"],
                "runtime_session_id": "session-" + request["request_id"], "runtime_event_id": "event-" + request["request_id"],
                "action": "runtime.turn." + status, "turn_status": status, "output_text": output}
        payload = {"data_root": self.root, "surface": "runtime_event", "body": body}
        return handle_scheduled(payload)

    def test_parallel_blocks_stop_and_join_requires_all_confirmed_checkpoints(self):
        chat = self.create()
        started = self.call("run", chat_id=chat["id"])
        requests = started["runtime_session_requests"]
        self.assertEqual(len(requests), 2)
        run_id = started["chat"]["run"]["id"]
        self.terminal(requests[0])
        waiting = self.call("read", chat_id=chat["id"])["chat"]
        self.assertEqual(waiting["run"]["status"], "checkpoint")
        with self.assertRaises(ValueError):
            self.call("continue", chat_id=chat["id"], run_id=run_id, node_ids=["join"])
        partial = self.call("continue", chat_id=chat["id"], run_id=run_id, node_ids=["a"])
        self.assertEqual(partial["runtime_session_requests"], [])
        self.terminal(requests[1])
        joined = self.call("continue", chat_id=chat["id"], run_id=run_id, node_ids=["b"])
        self.assertEqual(len(joined["runtime_session_requests"]), 1)
        prompt = joined["runtime_session_requests"][0]["input_text"]
        self.assertIn('"predecessor_outputs"', prompt)
        self.assertIn('"block_id": "a"', prompt)
        self.terminal(joined["runtime_session_requests"][0])
        finished = self.call("continue", chat_id=chat["id"], run_id=run_id, node_ids=["join"])
        self.assertEqual(finished["chat"]["run"]["status"], "completed")
        self.assertIsNotNone(finished["chat"]["run"]["finished_at"])

    def test_duplicate_terminal_and_stale_callbacks_cannot_advance_or_relaunch(self):
        chat = self.create()
        requests = self.call("run", chat_id=chat["id"])["runtime_session_requests"]
        self.terminal(requests[0])
        self.assertTrue(self.terminal(requests[0])["ignored"])
        result = tick(self.root, {"runtime_request_states": []})
        self.assertFalse(result.get("runtime_session_requests"))
        self.call("cancel", chat_id=chat["id"])
        self.terminal(requests[1])
        read = self.call("read", chat_id=chat["id"])["chat"]
        self.assertEqual(read["run"]["status"], "cancelled")

    def test_pause_interrupts_and_late_launch_callback_is_fenced(self):
        chat = self.create()
        request = self.call("run", chat_id=chat["id"])["runtime_session_requests"][0]
        self.call("pause", chat_id=chat["id"])
        callback = self.call("started", actor=None, surface="runtime_request_callback", dispatch_id=request["request_id"],
                             request_id=request["request_id"], runtime_request_status="submitted", runtime_session_id="s", turn_id="t")
        self.assertEqual(callback["runtime_turn_interrupt_requests"][0]["turn_id"], "t")
        self.assertFalse(tick(self.root, {"runtime_request_states": []}).get("runtime_session_requests"))
        with self.assertRaises(ValueError):
            self.call("run", chat_id=chat["id"])

    def test_atomic_tick_claim_and_exact_launch_replay(self):
        chat = self.call("create", title="Daily", graph=self.graph, schedule={"frequency": "daily", "timezone": "UTC"})["chat"]
        with connection(self.root, write=True) as db:
            db.execute("UPDATE scheduled_requests SET status='completed' WHERE kind='message'")
            db.execute("UPDATE scheduled_chats SET next_due=1 WHERE id=?", (chat["id"],))
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: tick(self.root, {"runtime_request_states": []}), range(2)))
        requests = [request for result in results for request in result.get("runtime_session_requests", [])]
        self.assertEqual(len(requests), 2)
        with connection(self.root, write=True) as db:
            db.execute("UPDATE scheduled_requests SET updated_at=1 WHERE kind='block'")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM scheduled_runs").fetchone()[0], 1)
        replayed = tick(self.root, {"runtime_request_states": []})["runtime_session_requests"]
        self.assertEqual({json.dumps(r, sort_keys=True) for r in requests}, {json.dumps(r, sort_keys=True) for r in replayed})

    def test_optimistic_revision_and_run_snapshot_lock(self):
        chat = self.create()
        updated = self.call("update", chat_id=chat["id"], expected_revision=1, title="Updated")["chat"]
        self.assertEqual(updated["revision"], 2)
        with self.assertRaises(ValueError):
            self.call("update", chat_id=chat["id"], expected_revision=1, title="Lost edit")
        self.call("run", chat_id=chat["id"])
        with self.assertRaises(ValueError):
            self.call("update", chat_id=chat["id"], expected_revision=2, title="During run")

    def test_actor_isolation_references_and_inbox_receipts(self):
        chat = self.create()
        with self.assertRaises(ValueError):
            self.call("read", actor="bob", chat_id=chat["id"])
        self.assertEqual(self.call("list", actor="bob")["chats"], [])
        resolved = scheduled_references({"data_root": self.root, "user_id": "bob", "body": {"action": "references.resolve", "entity_id": chat["id"]}})
        self.assertFalse(resolved["exists"])
        request = self.call("run", chat_id=chat["id"])["runtime_session_requests"][0]
        self.terminal(request)
        def inbox(actor, action="list", **fields):
            return handle_scheduled({"data_root": self.root, "user_id": actor, "body": {"action": "notifications." + action, **fields}})
        alice = inbox("alice")
        self.assertEqual(alice["unread_total"], 1)
        self.assertEqual(inbox("bob")["total"], 0)
        notification_id = alice["notifications"][0]["id"]
        with self.assertRaises(ValueError):
            inbox("bob", "dismiss", id=notification_id)
        inbox("alice", "read", id=notification_id)
        self.assertEqual(inbox("alice")["unread_total"], 0)
        inbox("alice", "dismiss", id=notification_id)
        self.assertEqual(inbox("alice")["total"], 0)

    def test_skills_and_runtime_envelope_are_explicit_and_owned(self):
        self.graph["nodes"][0]["skill_ids"] = ["research"]
        chat = self.create(workspace_profile_binding_id="model-selection", reasoning_effort="high")
        request = self.call("run", chat_id=chat["id"])["runtime_session_requests"][0]
        self.assertEqual(request["on_behalf_of_user_id"], "alice")
        self.assertEqual(request["idempotency_key"], request["request_id"])
        self.assertEqual(request["invoked_skill_ids"], ["research"])
        self.assertEqual(request["skill_activation_mode"], "explicit")
        self.assertEqual(request["workspace_profile_binding_id"], "model-selection")
        with self.assertRaises(PermissionError):
            self.call("started", dispatch_id=request["request_id"])

    def test_failed_predecessor_never_satisfies_dependency(self):
        chat = self.create()
        started = self.call("run", chat_id=chat["id"])
        self.terminal(started["runtime_session_requests"][0], status="failed")
        self.terminal(started["runtime_session_requests"][1])
        result = self.call("continue", chat_id=chat["id"], run_id=started["chat"]["run"]["id"], node_ids=["b"])
        self.assertFalse(result["runtime_session_requests"])
        retry = self.call("retry", chat_id=chat["id"], run_id=started["chat"]["run"]["id"], node_id="a")
        self.assertEqual(len(retry["runtime_session_requests"]), 1)
        self.assertNotEqual(retry["runtime_session_requests"][0]["request_id"], started["runtime_session_requests"][0]["request_id"])

    def test_contract_and_agent_surfaces(self):
        parsed = parse_app_contract_file(APP_ROOT)
        self.assertIn("chat_scheduled", parsed.contract.capabilities.mcp_tools)
        result = run_json_entrypoint(APP_ROOT / "mcp/server.py", payload={"data_root": self.root, "user_id": "alice", "tool_name": "chat_scheduled", "arguments": {"action": "create", "title": "AI graph", "graph": self.graph}}, cwd=APP_ROOT)
        self.assertEqual(result["status_code"], 200)
        self.assertTrue(result["queued"])
        self.assertNotIn("runtime_session_requests", result)
        chat_id = result["chat"]["id"]
        read = run_json_entrypoint(APP_ROOT / "cli/app_cli.py", payload={"data_root": self.root, "user_id": "alice", "command_id": "app.chat.scheduled", "arguments": {"action": "read", "chat_id": chat_id}}, cwd=APP_ROOT)
        self.assertEqual(read["chat"]["title"], "AI graph")

    def test_agent_outbox_pause_prevents_an_undispatched_turn(self):
        chat = self.create()
        result = self.call("run", chat_id=chat["id"])
        public = envelope(result, flattened=True, data_root=self.root)
        self.assertTrue(public["queued"])
        self.call("pause", chat_id=chat["id"])
        self.assertFalse(tick(self.root, {"runtime_request_states": []}).get("runtime_session_requests"))
        steps = self.call("read", chat_id=chat["id"])["chat"]["run"]["steps"]
        self.assertEqual([s["status"] for s in steps], ["cancelled", "cancelled", "pending"])

    def test_four_workspace_slots_and_reuse_immutable_skill_catalog(self):
        self.graph = {"nodes": [block("a")], "edges": []}
        self.graph["nodes"][0]["skill_ids"] = ["research"]
        chat = self.create(conversation_mode="reuse")
        result = self.call("run", chat_id=chat["id"])
        request = result["runtime_session_requests"][0]
        self.terminal(request)
        self.call("continue", chat_id=chat["id"], run_id=result["chat"]["run"]["id"], node_ids=["a"])
        reused = self.call("run", chat_id=chat["id"])["runtime_session_requests"][0]
        self.assertEqual(reused["runtime_session_id"], "session-" + request["request_id"])
        self.assertNotIn("skill_ids", reused)
        self.assertEqual(reused["invoked_skill_ids"], ["research"])
        for index in range(3):
            other = self.create(creation_id="other-" + str(index))
            self.call("run", chat_id=other["id"])
        limited = self.create(creation_id="limited")
        self.assertEqual(self.call("run", chat_id=limited["id"])["runtime_session_requests"], [])

    def test_deleted_runtime_chat_can_be_reinitialized_and_is_not_reused(self):
        created = self.call("create", title="Cleanup", graph=self.graph)
        request = created["runtime_session_requests"][0]
        self.terminal(request)
        chat_id = created["chat"]["id"]
        self.assertTrue(self.call("read", chat_id=chat_id)["chat"]["chat_session_id"])
        cleanup(self.root, ["session-" + request["request_id"]])
        chat = self.call("read", chat_id=chat_id)["chat"]
        self.assertEqual(chat["chat_session_id"], "")
        self.assertEqual(chat["message_status"], "failed")
        new = self.call("initialize", chat_id=chat_id)["runtime_session_requests"][0]
        self.assertNotEqual(new["request_id"], request["request_id"])


class ScheduledValidationTests(unittest.TestCase):
    def test_cycle_and_missing_prerequisites_rejected(self):
        graph = {"nodes": [block("a"), block("b")], "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]}
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_graph(graph)
        graph["edges"] = [{"source": "missing", "target": "b"}]
        with self.assertRaises(ValueError):
            validate_graph(graph)
        with self.assertRaises(ValueError):
            validate_graph({"nodes": [block("__schedule")], "edges": []})

    def test_weekdays_weekly_once_and_dst_are_timezone_aware(self):
        friday = datetime(2026, 10, 16, 12, tzinfo=UTC).timestamp()
        schedule = validate_schedule({"frequency": "weekdays", "timezone": "Europe/Rome", "time": "09:00"})
        self.assertEqual(datetime.fromtimestamp(next_due(schedule, friday), UTC), datetime(2026, 10, 19, 7, tzinfo=UTC))
        schedule = validate_schedule({"frequency": "daily", "timezone": "America/New_York", "time": "02:30"})
        spring = datetime(2026, 3, 8, 5, tzinfo=UTC).timestamp()
        self.assertEqual(datetime.fromtimestamp(next_due(schedule, spring), UTC), datetime(2026, 3, 8, 7, 30, tzinfo=UTC))
        schedule = validate_schedule({"frequency": "daily", "timezone": "America/New_York", "time": "01:30"})
        autumn = datetime(2026, 11, 1, 5, 45, tzinfo=UTC).timestamp()
        self.assertEqual(datetime.fromtimestamp(next_due(schedule, autumn), UTC), datetime(2026, 11, 2, 6, 30, tzinfo=UTC))


if __name__ == "__main__":
    unittest.main()
