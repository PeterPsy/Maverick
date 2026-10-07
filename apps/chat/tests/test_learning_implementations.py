"""Normal Chat handoff, bounded scheduling, provenance and recovery contracts."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from learning_service import handle_learning
from learning_store import connection, now


class ImplementationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        with connection(self.root, write=True) as db:
            for index in range(3):
                evidence = [{"session_id": f"source-{index}", "turn_id": f"turn-{index}", "role": "user", "quote": "A verified quote", "metrics": {}}]
                db.execute("""INSERT INTO learning_items(id,fingerprint,kind,title,body,status,evidence,details,updated_at)
                    VALUES(?,?,'improvement','Fix the issue','Observed failure','pending',?,?,?)""",
                    (str(index), str(index), json.dumps(evidence), json.dumps({"verification": "Run the regression check",
                        "policy_version": 2, "reviewed_sources": {f"source-{index}": f"turn-{index}"}}), now()))
                db.execute("INSERT INTO learning_item_sources VALUES(?,?,?)", (str(index), f"analysis-{index}", f"source-{index}"))
                db.execute("INSERT INTO learning_conversations(session_id,project_id,last_activity) VALUES(?,'',?)", (f"source-{index}", now()))
                db.execute("INSERT INTO learning_context(session_id,latest_turn_id) VALUES(?,?)", (f"source-{index}", f"turn-{index}"))

    def call(self, action="learning.read", surface="backend", **body):
        return handle_learning({"data_root": self.root, "surface": surface, "user_id": "owner", "workspace_role": "admin",
                                "body": {"action": action, **body}})

    def review(self, command, item="0"):
        return self.call("learning.review", item_id=item, command=command)

    def tick(self, **body):
        return self.call("backend.tick", surface="background_tick", **{"runtime_request_states": [], **body})

    def ticket(self, item="0"):
        return next(row for row in self.call()["items"] if row["id"] == item)["implementation"]

    def submitted(self, request, session="work-chat", state="submitted", **changes):
        return self.call("learning.implementation_started", surface="runtime_request_callback",
            **request["callback"]["payload"], request_id=request["request_id"], runtime_request_status=state,
            runtime_session_id=session, turn_id="work-turn", **changes)

    def terminal(self, action="completed", **changes):
        return self.call("runtime.turn." + action, surface="runtime_event", runtime_session_id="work-chat",
            turn_id="work-turn", session_kind="chat_root", thread_visibility="user", turn_status=action,
            input_text="Fix", output_text="Changed file.py. Regression check passed.", **changes)

    def test_accept_duplicates_and_parallel_ticks_create_one_request(self):
        self.review("accept")
        self.review("accept")
        self.assertEqual(self.ticket()["status"], "queued")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.tick(), range(4)))
        requests = [request for result in results for request in result.get("runtime_session_requests", [])]
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertTrue(request["create_stream"])
        self.assertEqual(request["on_behalf_of_user_id"], "owner")
        self.assertEqual(request["runtime_mode"], "agentic")
        self.assertIn("app_ref:chat/thread/source-0", request["input_text"])
        self.assertIn("analysis-0", request["input_text"])
        self.assertIn("Run the regression check", request["input_text"])
        self.assertEqual(request["app_references"][0]["entity_id"], "source-0")

    def test_queue_is_serial_and_completion_requires_verification(self):
        self.call("learning.configure", settings={"improvement_concurrency": 1})
        self.review("accept")
        self.review("accept", "1")
        first = self.tick()["runtime_session_requests"][0]
        self.submitted(first)
        self.assertNotIn("runtime_session_requests", self.tick())
        with self.assertRaises(ValueError):
            self.review("implemented")
        self.terminal()
        self.assertEqual(self.ticket()["status"], "awaiting_review")
        self.assertIn("Regression check", self.ticket()["summary"])
        second = self.tick()["runtime_session_requests"][0]
        self.assertNotEqual(first["request_id"], second["request_id"])
        self.review("implemented")
        self.assertEqual(self.ticket()["status"], "implemented")

    def test_retry_reuses_chat_and_fences_old_callbacks(self):
        self.review("accept")
        first = self.tick()["runtime_session_requests"][0]
        self.submitted(first)
        self.terminal("failed")
        self.review("retry")
        second = self.tick()["runtime_session_requests"][0]
        self.assertEqual(second["runtime_session_id"], "work-chat")
        self.assertNotEqual(first["request_id"], second["request_id"])
        self.assertEqual(self.submitted(first), {"ignored": True})
        self.assertEqual(self.ticket()["status"], "launching")

    def test_lost_callback_replays_immutable_key_and_recovers_ids(self):
        self.review("accept")
        first = self.tick()["runtime_session_requests"][0]
        with connection(self.root, write=True) as db:
            db.execute("UPDATE learning_implementations SET updated_at=0")
        replay = self.tick()["runtime_session_requests"][0]
        self.assertEqual(first, replay)
        self.submitted(replay)
        states = [{"request_id": replay["request_id"], "session_id": "work-chat", "turn_id": "work-turn", "status": "completed"}]
        self.tick(runtime_request_states=states)
        self.assertEqual(self.ticket()["status"], "awaiting_review")

    def test_recovery_correlates_lost_handoff_before_replaying_evidence(self):
        self.call("learning.configure", settings={"enabled": True})
        self.review("accept")
        request = self.tick()["runtime_session_requests"][0]
        terminal = {"action": "runtime.turn.completed", "runtime_request_id": request["request_id"],
                    "runtime_session_id": "work-chat", "turn_id": "work-turn", "turn_status": "completed",
                    "session_kind": "chat_root", "thread_visibility": "user", "completed_at": "2030-01-01T00:00:00+00:00",
                    "input_text": "Fix", "output_text": "Verified fix"}
        result = self.call("backend.recovery", surface="backend_recovery", recent_terminal_exchanges=[terminal],
                          runtime_request_states=[{"request_id": request["request_id"], "session_id": "work-chat", "turn_id": "work-turn", "status": "completed"}])
        self.assertNotIn("runtime_session_requests", result)
        self.assertEqual(self.ticket()["session_id"], "work-chat")
        self.assertEqual(self.ticket()["summary"], "Verified fix")
        self.assertEqual(self.ticket()["status"], "awaiting_review")
        self.assertEqual({x['session_id'] for x in self.call()['conversations']}, {'source-0', 'source-1', 'source-2'})

    def test_terminal_outbox_replay_does_not_repeat_ticket_mutations(self):
        self.review("accept")
        self.submitted(self.tick()["runtime_session_requests"][0])
        self.terminal(runtime_event_id="event-1")
        count = len(self.call()["audit"])
        self.assertEqual(self.terminal(runtime_event_id="event-1"), {"ignored": True})
        self.assertEqual(len(self.call()["audit"]), count)

    def test_stop_waits_for_terminal_before_releasing_slot(self):
        self.call("learning.configure", settings={"improvement_concurrency": 1})
        self.review("accept")
        first = self.tick()["runtime_session_requests"][0]
        self.review("stop")  # Stop may race with runtime submission.
        self.submitted(first)
        self.assertEqual(self.ticket()["status"], "stopping")
        self.review("accept", "1")
        stop = self.tick()
        self.assertEqual(stop["runtime_turn_interrupt_requests"][0]["turn_id"], "work-turn")
        self.assertNotIn("runtime_session_requests", stop)
        self.terminal("cancelled")
        self.assertIn("runtime_session_requests", self.tick())

    def test_generated_chat_and_followups_never_enter_learning(self):
        self.call("learning.configure", settings={"enabled": True})
        self.review("accept")
        self.submitted(self.tick()["runtime_session_requests"][0])
        self.terminal()
        self.call("runtime.turn.queued", surface="runtime_event", runtime_session_id="work-chat", turn_id="followup")
        self.call("runtime.turn.completed", surface="runtime_event", runtime_session_id="work-chat", turn_id="old-turn")
        self.assertEqual(self.ticket()["status"], "running")
        self.call("runtime.turn.completed", surface="runtime_event", runtime_session_id="work-chat", turn_id="followup", output_text="Follow-up fixed")
        self.assertEqual(self.ticket()["summary"], "Follow-up fixed")
        self.assertEqual({x['session_id'] for x in self.call()['conversations']}, {'source-0', 'source-1', 'source-2'})

    def test_legacy_acceptance_requires_explicit_start_and_callback_is_trusted(self):
        with connection(self.root, write=True) as db:
            db.execute("UPDATE learning_items SET status='accepted' WHERE id='0'")
        self.assertNotIn("runtime_session_requests", self.tick())
        self.review("start")
        self.assertIn("runtime_session_requests", self.tick())
        with self.assertRaises(PermissionError):
            self.call("learning.implementation_started", item_id="0")

    def test_deleted_work_chat_cancels_ticket_without_stalling_queue(self):
        self.review("accept")
        self.submitted(self.tick()["runtime_session_requests"][0])
        handle_learning({"data_root": self.root, "effective_mode": "full-access",
                         "body": {"action": "runtime.cleanup_sessions", "runtime_session_ids": ["work-chat"]}})
        self.assertEqual(self.ticket()["status"], "cancelled")
        self.review("accept", "1")
        self.assertIn("runtime_session_requests", self.tick())

    def test_unconfirmed_reservation_is_visible_and_stop_releases_capacity(self):
        self.review('accept')
        request=self.tick()['runtime_session_requests'][0]
        self.call('learning.implementation_started',surface='runtime_request_callback',item_id='0',request_id=request['request_id'],
                  runtime_request_status='reserving',runtime_session_id='',turn_id='')
        self.assertEqual(self.ticket()['status'],'failed')
        self.assertIn('reserved request',self.ticket()['error'])

    def test_old_backend_keeps_accepted_tickets_queued_until_runtime_handoff_is_ready(self):
        self.review('accept')
        result=self.call('backend.tick',surface='background_tick')
        self.assertNotIn('runtime_session_requests',result)
        self.assertEqual(self.ticket()['status'],'queued')
        self.assertFalse(self.call()['runtime_ready'])
        self.assertIn('runtime_session_requests',self.tick())

    def test_memory_is_serial_while_improvements_run_in_parallel_in_distinct_projects(self):
        with connection(self.root, write=True) as db:
            db.execute("UPDATE learning_items SET kind='memory',provider_id='memory' WHERE id IN ('0','1')")
        self.review('approve', '0')
        self.review('approve', '0')
        self.review('approve', '1')
        self.review('accept', '2')
        requests = self.tick()['runtime_session_requests']
        self.assertEqual(len(requests), 2)
        memory, improvement = requests
        self.assertNotEqual(memory['project_id'], improvement['project_id'])
        self.assertIn('chat_learning_memory', memory['input_text'])
        self.submitted(memory)
        self.submitted(improvement, session='fix-chat')
        self.assertNotIn('runtime_session_requests', self.tick())
        self.assertEqual(self.ticket('1')['status'], 'queued')
        result = handle_learning({'data_root': self.root, 'surface': 'mcp', 'runtime_session_id':'work-chat',
                                  'body': {'action':'learning.memory_agent','item_id':'0','command':'commit'}})
        save = result['dependency_backend_requests'][0]
        self.assertEqual(save['provider_app_id'], 'memory')
        self.call('learning.memory_saved', surface='dependency_backend_request_callback', **save['callback']['payload'],
                  dependency_backend_status='completed', dependency_backend_result={'status_code':200,'dependency_provider_app_id':'memory','json':{'node':{'id':'saved-node','updated_at':'revision'}}})
        self.assertEqual(self.ticket()['status'], 'running')  # The first chat is still finishing.
        self.assertNotIn('runtime_session_requests', self.tick())
        self.terminal()
        self.assertEqual(self.ticket()['status'], 'saved')
        self.assertIn('runtime_session_requests', self.tick())

    def test_parallel_improvements_are_claimed_once_and_memory_chat_cannot_write_another_candidate(self):
        self.review('accept','0')
        self.review('accept','1')
        self.review('accept','2')
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.tick(),range(4)))
        self.assertEqual(sum(len(result.get('runtime_session_requests',[])) for result in results),3)
        with self.assertRaises(PermissionError):
            handle_learning({'data_root':self.root,'surface':'mcp','runtime_session_id':'source-0',
                             'body':{'action':'learning.memory_agent','item_id':'0','command':'commit'}})

    def test_stale_oldest_ticket_does_not_block_a_ready_ticket(self):
        self.call('learning.configure', settings={'improvement_concurrency':1})
        self.review('accept', '0')
        self.review('accept', '1')
        with connection(self.root, write=True) as db:
            db.execute("UPDATE learning_items SET details=? WHERE id='0'", (json.dumps({'policy_version':2,'review_stale':True}),))
        requests = self.tick()['runtime_session_requests']
        self.assertEqual([x['callback']['payload']['item_id'] for x in requests], ['1'])
        self.assertEqual(self.ticket('0')['status'], 'queued')

    def test_memory_turn_completion_without_provider_receipt_is_not_saved(self):
        with connection(self.root,write=True) as db:
            db.execute("UPDATE learning_items SET kind='memory',provider_id='memory' WHERE id='0'")
        self.review('approve')
        self.submitted(self.tick()['runtime_session_requests'][0])
        self.terminal()
        self.assertEqual(self.ticket()['status'],'failed')
        self.assertEqual(next(item for item in self.call()['items'] if item['id']=='0')['status'],'accepted')
        self.assertIn('without a verified Memory save',self.ticket()['error'])

    def test_memory_commit_is_scoped_idempotent_and_uses_pinned_destination(self):
        from core.shared.entrypoints import run_json_entrypoint
        with connection(self.root,write=True) as db:
            db.execute("UPDATE learning_items SET kind='memory',provider_id='pinned-memory',details=? WHERE id='0'", (json.dumps({'policy_version':2,
                'reviewed_sources': {'source-0': 'turn-0'}, 'memory_matches':[{'id':'existing','title':'Related fact'}]}),))
        self.call('learning.review',item_id='0',command='approve',target_node_id='existing')
        self.submitted(self.tick()['runtime_session_requests'][0])
        entrypoint=Path(__file__).resolve().parents[1]/'mcp'/'server.py'
        payload={'surface':'mcp','data_root':self.root,'tool_name':'chat_learning_memory','runtime_session_id':'work-chat',
                 'arguments':{'item_id':'0','command':'commit'}}
        result=run_json_entrypoint(entrypoint,payload=payload,cwd=entrypoint.parent)
        save=result['dependency_backend_requests'][0]
        self.assertEqual(save['provider_app_id'],'pinned-memory')
        self.assertEqual(save['body']['node_id'],'existing')
        self.assertEqual(save['body']['source_key'],'conversation-learning:0')
        self.assertIn('A verified quote',save['body']['body_markdown'])
        replay=run_json_entrypoint(entrypoint,payload=payload,cwd=entrypoint.parent)
        self.assertNotIn('dependency_backend_requests',replay)
        foreign=run_json_entrypoint(entrypoint,payload={**payload,'runtime_session_id':'other-chat'},cwd=entrypoint.parent)
        self.assertEqual(foreign['status_code'],403)

    def test_replayed_completed_memory_handoff_reports_missing_save(self):
        with connection(self.root, write=True) as db:
            db.execute("UPDATE learning_items SET kind='memory',provider_id='memory' WHERE id='0'")
        self.review('approve')
        request = self.tick()['runtime_session_requests'][0]
        self.submitted(request, state='completed')
        self.assertEqual(self.ticket()['status'], 'failed')
        self.assertIn('without a verified Memory save', self.ticket()['error'])


if __name__ == "__main__":
    unittest.main()
