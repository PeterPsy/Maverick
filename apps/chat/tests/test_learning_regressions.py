"""Regressions for reassessment, automatic Memory, paused work and deleted sources."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from learning_memory import memory_callback
from learning_queue import capture, tick
from learning_reconciliation import current_review
from learning_results import complete_analysis
from learning_service import handle_learning
from learning_store import connection, now
from test_conversation_learning import analysis_output, candidate


class LearningRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.call('learning.configure', settings={'enabled': True, 'idle_seconds': 0})

    def call(self, action='learning.read', surface='backend', **body):
        return handle_learning({'data_root': self.root, 'surface': surface, 'workspace_role': 'admin',
            'user_id': 'owner', 'body': {'action': action, **body}})

    def capture(self, turn='turn-1', session='source', **changes):
        return capture(self.root, {'runtime_session_id': session, 'turn_id': turn,
            'action': 'runtime.turn.completed', 'turn_status': 'completed', 'session_kind': 'chat_root',
            'thread_visibility': 'user', 'project_id': '', 'input_text': 'Marco vive a Milano da dieci anni.',
            'output_text': 'La ricerca è completata e verificata.', 'metrics': {}, **changes})

    def start(self):
        return tick(self.root, {'runtime_status_complete': True})['background_generation_requests'][0]

    def finish(self, request, **changes):
        return complete_analysis(self.root, {**request['callback']['payload'], 'request_id': request['request_id'],
            'status': 'completed', 'output_text': json.dumps(analysis_output(json.loads(request['input_text']), **changes)),
            'usage': {'total_tokens': 50}})

    def proposal(self, turn='turn-1'):
        return candidate('La ricerca è completata e verificata.', scope='maverick', memory_type='none',
            problem_kind='reliability', generalization='Prevent failures across workspace tasks',
            verification='Reproduce and verify the failure',
            evidence=[{'turn_id': turn, 'role': 'assistant', 'quote': 'La ricerca è completata e verificata.'}])

    def publish_proposal(self):
        self.capture()
        self.finish(self.start(), improvements=[self.proposal()])
        return self.call()['items'][0]

    def publish_memory(self):
        self.capture()
        fact = candidate('Marco vive a Milano da dieci anni.', memory_type='person')
        check = self.finish(self.start(), memory=[fact])['dependency_backend_requests'][0]
        memory_callback(self.root, {**check['callback']['payload'], 'action': 'learning.memory_checked',
            'dependency_backend_status': 'completed', 'dependency_backend_result': {'status_code': 200,
            'dependency_provider_app_id': 'memory', 'json': {'results': []}}})
        item = self.call()['items'][0]
        self.call('learning.review', item_id=item['id'], command='approve')
        request = self.runtime_tick()['runtime_session_requests'][0]
        self.call('learning.implementation_started', surface='runtime_request_callback', **request['callback']['payload'],
            request_id=request['request_id'], runtime_request_status='submitted', runtime_session_id='memory-work', turn_id='work-turn')
        return item

    def runtime_tick(self):
        return handle_learning({'data_root': self.root, 'surface': 'background_tick',
            'body': {'action': 'backend.tick', 'runtime_request_states': [], 'runtime_status_complete': True}})

    def cleanup(self, *sessions):
        return handle_learning({'data_root': self.root, 'effective_mode': 'full-access',
            'body': {'action': 'runtime.cleanup_sessions', 'runtime_session_ids': list(sessions)}})

    def test_reassessment_ticks_preserve_deadline_and_running_claim(self):
        item = self.publish_proposal()
        self.call('learning.review', item_id=item['id'], command='accept')
        self.call('learning.configure', settings={'idle_seconds': 120})
        timestamp = now()
        with patch('learning_queue.now', return_value=timestamp) as queue_clock, \
                patch('learning_implementations.now', return_value=timestamp) as ticket_clock:
            self.capture('turn-2')
            for elapsed in (0, 30, 60, 90):
                queue_clock.return_value = ticket_clock.return_value = timestamp + elapsed
                result = self.runtime_tick()
                self.assertNotIn('runtime_session_requests', result)
                self.assertNotIn('background_generation_requests', result)
                with connection(self.root) as db:
                    jobs = db.execute("SELECT * FROM learning_jobs WHERE status='queued'").fetchall()
                    self.assertEqual(len(jobs), 1)
                    self.assertEqual(jobs[0]['due'], timestamp + 120)
            queue_clock.return_value = ticket_clock.return_value = timestamp + 120
            request = self.runtime_tick()['background_generation_requests'][0]
            for elapsed in (150, 180, 240):
                queue_clock.return_value = ticket_clock.return_value = timestamp + elapsed
                result = self.runtime_tick()
                self.assertNotIn('background_generation_requests', result)
                with connection(self.root) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM learning_jobs WHERE status IN ('queued','running')").fetchone()[0], 1)
            self.finish(request, reconciliations=[{'item_id': item['id'], 'disposition': 'keep',
                'reason': 'The issue remains relevant after the new completed outcome',
                'evidence': [{'turn_id': 'turn-2', 'role': 'assistant', 'quote': 'La ricerca è completata e verificata.'}]}])
            self.assertEqual(len(self.runtime_tick()['runtime_session_requests']), 1)
            self.assertNotIn('runtime_session_requests', self.runtime_tick())

    def test_manual_analysis_is_not_delayed_by_reassessment_ticks(self):
        item = self.publish_proposal()
        self.call('learning.review', item_id=item['id'], command='accept')
        self.call('learning.configure', settings={'idle_seconds': 120})
        self.capture('turn-2')
        self.call('learning.analyze_now', session_id='source')
        result = self.runtime_tick()
        self.assertNotIn('runtime_session_requests', result)
        self.assertEqual(len(result['background_generation_requests']), 1)

    def test_new_terminal_evidence_still_restarts_the_idle_window(self):
        item = self.publish_proposal()
        self.call('learning.review', item_id=item['id'], command='accept')
        self.call('learning.configure', settings={'idle_seconds': 120})
        timestamp = now()
        with patch('learning_queue.now', return_value=timestamp) as queue_clock, \
                patch('learning_implementations.now', return_value=timestamp) as ticket_clock:
            self.capture('turn-2')
            self.runtime_tick()
            queue_clock.return_value = ticket_clock.return_value = timestamp + 60
            self.capture('turn-3')
            queue_clock.return_value = ticket_clock.return_value = timestamp + 120
            self.assertNotIn('background_generation_requests', self.runtime_tick())
            queue_clock.return_value = ticket_clock.return_value = timestamp + 180
            request = self.runtime_tick()['background_generation_requests'][0]
            self.assertEqual([x['turn_id'] for x in json.loads(request['input_text'])['exchanges']], ['turn-2', 'turn-3'])

    def test_ticket_polling_does_not_retry_cancelled_analysis(self):
        item = self.publish_proposal()
        self.call('learning.review', item_id=item['id'], command='accept')
        self.capture('turn-2')
        job = next(x for x in self.call()['jobs'] if x['status'] == 'queued')
        self.call('learning.job', job_id=job['id'], command='cancel')
        for _ in range(3):
            self.assertNotIn('background_generation_requests', self.runtime_tick())
        self.assertEqual(len(self.call()['jobs']), 2)

    def test_assistant_research_requires_agent_verification_even_with_explicit_flag(self):
        text = 'Marco dirige Example, secondo https://example.com/team. Ricerca completata.'
        for index, user_quote in enumerate(('', 'Ho completato la ricerca.', text)):
            with self.subTest(user_quote=user_quote):
                self.root = str(Path(self.temp.name) / f'case-{index}')
                self.call('learning.configure', settings={'enabled': True, 'idle_seconds': 0, 'memory_mode': 'automatic'})
                turn, session = f'turn-{index}', f'research-{index}'
                self.capture(turn, session, input_text=user_quote, output_text=text)
                evidence = [{'turn_id': turn, 'role': 'assistant', 'quote': text}]
                if user_quote:
                    evidence.append({'turn_id': turn, 'role': 'user', 'quote': user_quote})
                fact = candidate(text, dedupe_key=f'research-{index}', memory_type='research', explicit=True,
                    source_refs=['https://example.com/team'], evidence=evidence)
                check = self.finish(self.start(), memory=[fact])['dependency_backend_requests'][0]
                response = memory_callback(self.root, {**check['callback']['payload'], 'action': 'learning.memory_checked',
                    'dependency_backend_status': 'completed', 'dependency_backend_result': {'status_code': 200,
                    'dependency_provider_app_id': 'memory', 'json': {'results': []}}})
                self.assertNotIn('dependency_backend_requests', response)
                item = next(x for x in self.call()['items'] if x['id'] == check['callback']['payload']['item_id'])
                self.assertEqual(item['status'], 'pending')
                self.call('learning.review', item_id=item['id'], command='approve')
                request = self.runtime_tick()['runtime_session_requests'][0]
                self.assertIn('https://example.com/team', request['input_text'])
                self.call('learning.review', item_id=item['id'], command='stop')

    def test_paused_open_episodes_remain_in_other_chat_context(self):
        for index, status in enumerate(('ongoing', 'blocked', 'uncertain', 'completed')):
            session = f'other-{status}'
            self.capture(f'other-turn-{index}', session, input_text='Implementa il supporto XLS.',
                output_text='Restano implementazione e test.' if status != 'completed' else 'Implementazione e test completati.')
            request = self.start()
            output = analysis_output(json.loads(request['input_text']))
            output['episode'].update(status=status, summary='Work on XLS support',
                open_work=['Implement XLS support', 'Run tests'] if status != 'completed' else [])
            self.finish(request, episode=output['episode'])
        self.capture()
        data = json.loads(self.start()['input_text'])
        work = {x['session_id']: x for x in data['current_work']}
        self.assertEqual(set(work), {'other-ongoing', 'other-blocked', 'other-uncertain'})
        for status in ('ongoing', 'blocked', 'uncertain'):
            self.assertEqual(work[f'other-{status}']['episode_state'], {'status': status,
                'summary': 'Work on XLS support', 'open_work': ['Implement XLS support', 'Run tests']})

    def test_current_work_filters_excluded_chats_before_the_limit(self):
        self.capture('visible-turn', 'visible')
        request = self.start()
        output = analysis_output(json.loads(request['input_text']))
        output['episode'].update(status='ongoing', summary='Implementation underway', open_work=['Run tests'])
        self.finish(request, episode=output['episode'])
        excluded = [f'excluded-{index}' for index in range(9)]
        for session in excluded:
            self.capture(session, session, action='runtime.turn.queued', input_text='Private implementation')
        self.capture('private-project-turn', 'private-project', action='runtime.turn.queued', project_id='private')
        self.call('learning.configure', settings={'excluded_thread_ids': excluded,
            'excluded_project_ids': ['private'], 'max_context_chars': 4000})
        self.capture()
        request = self.start()
        self.assertLessEqual(len(request['input_text']), 4000)
        self.assertEqual([x['session_id'] for x in json.loads(request['input_text'])['current_work']], ['visible'])

    def test_missing_source_blocks_launch_even_without_cleanup(self):
        item = self.publish_proposal()
        self.call('learning.review', item_id=item['id'], command='accept')
        with connection(self.root, write=True) as db:
            db.execute("DELETE FROM learning_conversations WHERE session_id='source'")
            self.assertFalse(current_review(db, db.execute('SELECT * FROM learning_items WHERE id=?', (item['id'],)).fetchone()))
        self.assertNotIn('runtime_session_requests', self.runtime_tick())

    def test_source_cleanup_rejects_accepted_item_and_cancels_queued_ticket(self):
        item = self.publish_proposal()
        self.call('learning.review', item_id=item['id'], command='accept')
        self.cleanup('source')
        item = self.call()['items'][0]
        self.assertEqual(item['status'], 'rejected')
        self.assertEqual(item['evidence'], [])
        self.assertEqual(item['implementation']['status'], 'cancelled')
        self.assertNotIn('runtime_session_requests', self.runtime_tick())

    def test_remaining_source_requires_reassessment_and_has_no_deleted_links(self):
        item = self.publish_proposal()
        self.capture('other-turn', 'other')
        self.finish(self.start(), improvements=[self.proposal('other-turn')])
        self.call('learning.review', item_id=item['id'], command='accept')
        self.cleanup('source')
        item = self.call()['items'][0]
        self.assertEqual(item['status'], 'accepted')
        self.assertEqual(item['implementation']['status'], 'queued')
        self.assertTrue(item['details']['review_stale'])
        self.assertEqual({x['session_id'] for x in item['evidence']}, {'other'})
        self.assertEqual(set(item['details']['reviewed_sources']), {'other'})
        self.assertNotIn('runtime_session_requests', self.runtime_tick())
        self.capture('other-turn-2', 'other')
        self.finish(self.start(), reconciliations=[{'item_id': item['id'], 'disposition': 'keep',
            'reason': 'The remaining evidence still supports this improvement',
            'evidence': [{'turn_id': 'other-turn-2', 'role': 'assistant', 'quote': 'La ricerca è completata e verificata.'}]}])
        request = self.runtime_tick()['runtime_session_requests'][0]
        self.assertNotIn('app_ref:chat/thread/source', request['input_text'])
        self.assertEqual({x['entity_id'] for x in request['app_references']}, {'other'})

    def test_source_deletion_blocks_an_already_running_memory_commit(self):
        item = self.publish_memory()
        self.cleanup('source')
        self.assertEqual(self.call()['items'][0]['implementation']['status'], 'running')
        with self.assertRaisesRegex(ValueError, 'source conversation changed'):
            handle_learning({'data_root': self.root, 'surface': 'mcp', 'runtime_session_id': 'memory-work',
                'body': {'action': 'learning.memory_agent', 'item_id': item['id'], 'command': 'commit'}})

    def test_source_cleanup_preserves_saved_memory_provenance_and_undo(self):
        item = self.publish_memory()
        request = handle_learning({'data_root': self.root, 'surface': 'mcp', 'runtime_session_id': 'memory-work',
            'body': {'action': 'learning.memory_agent', 'item_id': item['id'], 'command': 'commit'}})['dependency_backend_requests'][0]
        memory_callback(self.root, {**request['callback']['payload'], 'action': 'learning.memory_saved',
            'dependency_backend_status': 'completed', 'dependency_backend_result': {'status_code': 200,
            'dependency_provider_app_id': 'memory', 'json': {'node': {'id': 'saved-node', 'updated_at': 'revision'}}}})
        self.cleanup('source')
        saved = self.call()['items'][0]
        self.assertEqual(saved['status'], 'saved')
        self.assertEqual(saved['evidence'], item['evidence'])
        undo = self.call('learning.review', item_id=item['id'], command='undo')['dependency_backend_requests'][0]
        self.assertEqual(undo['body']['expected_updated_at'], 'revision')


if __name__ == '__main__':
    unittest.main()
