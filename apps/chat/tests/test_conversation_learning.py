"""Evidence, queue recovery and review behavior for Conversation Learning."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sys
import tempfile
import unittest

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
sys.path.insert(0, str(BACKEND))
from learning_service import handle_learning
from learning_queue import capture, tick
from learning_results import complete_analysis
from learning_memory import memory_callback
from learning_store import connection, now
from learning_validation import validated_items
from core.shared.entrypoints import run_json_entrypoint


def candidate(quote='Preferisco risposte brevi e in italiano.', **changes):
    return {"title": "Lingua e stile", "body": quote, "dedupe_key": "user-language-style", "confidence": .99,
            "explicit": True, "category": "preference", "expected_impact": "", "effort": "", "verification": "",
            "evidence": [{"turn_id": "turn-1", "role": "user", "quote": quote}], **changes}


class ConversationLearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.configure(enabled=True, idle_seconds=0)

    def admin(self, action, **body):
        return handle_learning({"data_root": str(self.root), "surface": "backend", "workspace_role": "admin", "user_id": "owner",
                                "body": {"action": action, **body}})

    def configure(self, **settings):
        return self.admin('learning.configure', settings=settings)

    def capture(self, turn='turn-1', session='chat-1', **changes):
        return capture(self.root, {"runtime_session_id": session, "turn_id": turn, "action": "runtime.turn.completed",
            "turn_status": "completed", "session_kind": "chat_root", "thread_visibility": "user", "project_id": "",
            "input_text": "Preferisco risposte brevi e in italiano.", "output_text": "Terrò conto della preferenza.",
            "metrics": {"duration_seconds": 2}, **changes})

    def start(self):
        result = tick(self.root, {"runtime_status_complete": True, "busy_runtime_session_ids": []})
        return result['background_generation_requests'][0]

    def finish(self, request, memory=None, improvements=None, **changes):
        return complete_analysis(self.root, {**request['callback']['payload'], "request_id": request['request_id'],
            "status": "completed", "output_text": json.dumps({"memory": memory or [], "improvements": improvements or []}),
            "usage": {"total_tokens": 50}, **changes})

    def data(self):
        return self.admin('learning.read')

    def check(self, request, results=None, provider='memory'):
        return memory_callback(self.root, {**request['callback']['payload'], "action": request['callback']['action'],
            "dependency_backend_status": "completed", "dependency_backend_result": {"status_code": 200,
            "dependency_provider_app_id": provider, "json": {"results": results or []}}})

    def test_disabled_excluded_hidden_and_derived_chats_are_not_captured(self):
        self.configure(enabled=False)
        self.capture()
        self.configure(enabled=True, excluded_thread_ids=['excluded'], excluded_project_ids=['private'])
        self.capture(session='excluded')
        self.capture(session='project', project_id='private')
        self.capture(session='hidden', thread_visibility='hidden')
        self.capture(session='derived', session_kind='agent')
        self.assertEqual(self.data()['conversations'], [])

    def test_debounce_and_orchestration_busyness_prevent_claim(self):
        self.configure(idle_seconds=120)
        self.capture()
        self.assertNotIn('background_generation_requests', tick(self.root, {}))
        self.admin('learning.analyze_now', session_id='chat-1')
        self.assertNotIn('background_generation_requests', tick(self.root, {'busy_runtime_session_ids': ['chat-1']}))

    def test_duplicate_callbacks_and_simultaneous_ticks_claim_only_once(self):
        self.capture()
        self.capture()
        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(lambda _: tick(self.root, {}), range(6)))
        self.assertEqual(sum(bool(r.get('background_generation_requests')) for r in responses), 1)
        self.assertEqual(len(self.data()['jobs']), 1)
        with connection(self.root) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM learning_exchanges').fetchone()[0], 1)

    def test_new_turn_during_analysis_is_not_consumed_or_overwritten(self):
        self.capture()
        first = self.start()
        self.capture(turn='turn-2')
        self.finish(first)
        second = self.start()
        self.assertEqual([x['turn_id'] for x in json.loads(second['input_text'])['exchanges']], ['turn-2'])
        self.assertTrue(json.loads(second['input_text'])['prior_context'])
        self.assertEqual(self.finish(first), {'ignored': True})

    def test_recovery_cancel_and_retry_fence_old_results(self):
        self.capture()
        old = self.start()
        recovered = tick(self.root, {'action': 'backend.recovery'})
        self.assertNotIn('background_generation_requests', recovered)
        current = self.start()
        self.assertEqual(self.finish(old, [candidate()]), {'ignored': True})
        self.admin('learning.job', job_id=current['callback']['payload']['job_id'], command='cancel')
        self.assertEqual(self.finish(current), {'ignored': True})
        self.admin('learning.job', job_id=current['callback']['payload']['job_id'], command='retry')
        next_run = self.start()
        self.finish(next_run)
        self.assertEqual(self.data()['jobs'][0]['status'], 'completed')

    def test_new_user_message_cancels_analysis_before_its_next_attempt(self):
        self.capture()
        request = self.start()
        result = self.capture(turn='turn-2', action='runtime.turn.queued')
        self.assertEqual(result['background_generation_cancel_requests'], [request['request_id']])
        self.assertEqual(self.finish(request), {'ignored': True})
        admission = handle_learning({'data_root': str(self.root), 'surface': 'background_generation_admission',
            'body': {'action':'learning.analysis_admit', 'request_id':request['request_id'], **request['callback']['payload']}})
        self.assertFalse(admission['allowed'])

    def test_busy_slot_refunds_reservation_and_does_not_use_retry(self):
        self.capture()
        run = self.start()
        self.assertGreater(self.data()['daily_tokens_reserved_or_used'], 0)
        self.finish(run, status='busy')
        data = self.data()
        self.assertEqual(data['jobs'][0]['attempts'], 0)
        self.assertEqual(data['daily_tokens_reserved_or_used'], 0)

    def test_retry_limit_and_daily_budget_bound_work(self):
        self.capture()
        self.configure(daily_token_budget=1000)
        self.assertTrue(tick(self.root, {}).get('budget_exhausted'))
        self.configure(daily_token_budget=100000)
        for _ in range(3):
            run = self.start()
            self.finish(run, status='failed')
            with connection(self.root, write=True) as db:
                db.execute('UPDATE learning_jobs SET due=0')
        self.assertEqual(self.data()['jobs'][0]['status'], 'failed')
        self.assertGreater(self.data()['daily_tokens_reserved_or_used'], 3 * 2048)

    def test_context_limit_is_enforced_for_unicode_and_long_turns(self):
        self.configure(max_context_chars=4000)
        self.capture(input_text='à漢字' * 16000, output_text='test' * 16000)
        run = self.start()
        self.assertLessEqual(len(run['input_text']), 4000)

    def test_unversioned_queue_migration_preserves_interrupted_work(self):
        self.capture()
        with connection(self.root, write=True) as db:
            db.execute('ALTER TABLE learning_jobs DROP COLUMN reservation_day')
            db.execute('PRAGMA user_version=0')
        self.assertEqual(len(self.data()['jobs']), 1)
        self.assertTrue(self.start()['request_id'])

    def test_retention_still_runs_when_disabled_and_sensitive_values_are_redacted(self):
        self.capture(input_text='password=private-value and {"token": "private-token"}')
        run = self.start()
        self.assertNotIn('private-value', run['input_text'])
        self.assertNotIn('private-token', run['input_text'])
        self.finish(run)
        self.configure(enabled=False, retention_days=1)
        with connection(self.root, write=True) as db:
            db.execute('UPDATE learning_exchanges SET created_at=?', (now()-172800,))
            db.execute('UPDATE learning_jobs SET updated_at=?', (now()-172800,))
        tick(self.root,{})
        with connection(self.root) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM learning_exchanges').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT input_json FROM learning_jobs').fetchone()[0],'{}')

    def test_hallucinated_quotes_assistant_facts_and_invalid_metadata_rejected(self):
        self.capture()
        run = self.start()
        evidence = json.loads(run['input_text'])
        for bad in [candidate('Un fatto inesistente.'), candidate(explicit='yes'), candidate(category={}), candidate(dedupe_key='!!!'),
                    candidate(evidence=[{'turn_id':'turn-1','role':'assistant','quote':'Terrò conto della preferenza.'}])]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validated_items(json.dumps({'memory':[bad], 'improvements':[]}), evidence)
        evidence['exchanges'][0]['status'] = 'failed'
        with self.assertRaises(ValueError):
            validated_items(json.dumps({'memory':[candidate()], 'improvements':[]}), evidence)

    def test_review_first_provider_pin_and_stale_memory_callback_fence(self):
        self.capture()
        check = self.finish(self.start(), [candidate()])['dependency_backend_requests'][0]
        stale = {**check['callback']['payload'], 'operation_id': 'stale', 'action': 'learning.memory_checked'}
        self.assertEqual(memory_callback(self.root, stale), {'ignored': True})
        self.assertEqual(self.check(check, provider='memory-original'), {})
        item = self.data()['items'][0]
        self.assertEqual(item['status'], 'pending')
        result = self.admin('learning.review', item_id=item['id'], command='approve')
        save = result['dependency_backend_requests'][0]
        self.assertEqual(save['provider_app_id'], 'memory-original')
        self.assertEqual(save['body']['source_key'], 'conversation-learning:' + item['id'])
        with self.assertRaises(ValueError):
            self.admin('learning.review', item_id=item['id'], command='approve')
        saved = memory_callback(self.root, {**save['callback']['payload'], 'action':'learning.memory_saved',
            'dependency_backend_status':'completed', 'dependency_backend_result':{'status_code':200,
            'dependency_provider_app_id':'memory-original', 'json':{'node':{'id':'node-1','updated_at':'rev-1'}}}})
        self.assertEqual(saved, {})
        undo = self.admin('learning.review', item_id=item['id'], command='undo')['dependency_backend_requests'][0]
        self.assertEqual(undo['body']['expected_updated_at'], 'rev-1')
        self.assertEqual(undo['provider_app_id'], 'memory-original')

    def test_automatic_mode_requires_verbatim_fact_and_no_existing_match(self):
        self.configure(memory_mode='automatic')
        self.capture()
        check = self.finish(self.start(), [candidate()])['dependency_backend_requests'][0]
        self.assertIn('dependency_backend_requests', self.check(check))
        self.capture(turn='turn-2', session='chat-2')
        other = candidate(body='Una preferenza parafrasata', evidence=[{'turn_id':'turn-2','role':'user','quote':'Preferisco risposte brevi e in italiano.'}])
        check = self.finish(self.start(), [other])['dependency_backend_requests'][0]
        self.assertEqual(self.check(check), {})
        item = next(x for x in self.data()['items'] if x['body']==other['body'])
        self.assertEqual(item['status'], 'pending')

    def test_existing_match_requires_deliberate_destination(self):
        self.configure(memory_mode='automatic')
        self.capture()
        check = self.finish(self.start(), [candidate()])['dependency_backend_requests'][0]
        self.assertEqual(self.check(check, [{'id':'existing','title':'Preferenza'}]), {})
        item = self.data()['items'][0]
        with self.assertRaises(ValueError):
            self.admin('learning.review', item_id=item['id'], command='approve')
        save = self.admin('learning.review', item_id=item['id'], command='approve', target_node_id='existing')
        self.assertEqual(save['dependency_backend_requests'][0]['body']['node_id'], 'existing')

    def test_proposals_are_reviewed_and_duplicate_evidence_aggregated(self):
        self.capture()
        self.finish(self.start(), improvements=[candidate(category='feature')])
        self.capture(turn='turn-2')
        item = candidate(evidence=[{'turn_id':'turn-2','role':'user','quote':'Preferisco risposte brevi e in italiano.'}])
        self.finish(self.start(), improvements=[item])
        proposal = self.data()['items'][0]
        self.assertEqual(proposal['occurrences'], 2)
        self.admin('learning.review', item_id=proposal['id'], command='accept')
        self.admin('learning.review', item_id=proposal['id'], command='implemented')
        self.assertEqual(self.data()['items'][0]['status'], 'implemented')

    def test_pause_cleanup_and_admin_authority(self):
        self.capture()
        run = self.start()
        self.configure(paused=True)
        self.assertEqual(self.finish(run), {'ignored':True})
        self.assertNotIn('background_generation_requests', tick(self.root, {}))
        for action in ['learning.read', 'learning.analysis_completed', 'learning.memory_checked']:
            with self.assertRaises(PermissionError):
                handle_learning({'data_root':str(self.root), 'surface':'backend','body':{'action':action}})
        handle_learning({'data_root':str(self.root),'effective_mode':'full-access','body':{'action':'runtime.cleanup_sessions','runtime_session_ids':['chat-1']}})
        self.assertEqual(self.data()['conversations'], [])

    def test_read_and_idle_ticks_do_not_emit_data_change_events(self):
        for body, surface in [({'action':'learning.read'}, 'backend'), ({'action':'background.tick'}, 'background_tick')]:
            result = run_json_entrypoint(BACKEND/'app_backend.py', payload={'data_root':str(self.root),'workspace_role':'admin','surface':surface,'body':body}, cwd=BACKEND.parent)
            self.assertEqual(result['status_code'],200)
            self.assertNotIn('app_events',result)
