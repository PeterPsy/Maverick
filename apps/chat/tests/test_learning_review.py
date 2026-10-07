"""Episode closure, product relevance, sourced knowledge and backlog retirement."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from learning_service import handle_learning
from learning_queue import capture, tick
from learning_results import complete_analysis
from learning_store import connection, now
from learning_validation import review_output
from core.shared.entrypoints import run_json_entrypoint
from test_conversation_learning import candidate, analysis_output


class LearningReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.call('learning.configure', settings={'enabled': True, 'idle_seconds': 0})

    def call(self, action='learning.read', **body):
        return handle_learning({'data_root': self.root, 'surface': 'backend', 'workspace_role': 'admin', 'user_id': 'owner',
                                'body': {'action': action, **body}})

    def capture(self, turn='turn-1', **changes):
        return capture(self.root, {'runtime_session_id': 'source', 'turn_id': turn, 'action': 'runtime.turn.completed',
            'turn_status': 'completed', 'session_kind': 'chat_root', 'thread_visibility': 'user', 'project_id': '',
            'input_text': 'Ho completato la ricerca sulla persona.', 'output_text': 'La ricerca è completata e verificata.',
            'metrics': {}, **changes})

    def start(self):
        return tick(self.root, {'runtime_status_complete': True, 'busy_runtime_session_ids': []})['background_generation_requests'][0]

    def finish(self, request, output):
        return complete_analysis(self.root, {**request['callback']['payload'], 'request_id': request['request_id'],
            'status': 'completed', 'output_text': json.dumps(output), 'usage': {'total_tokens': 50}})

    def proposal(self, quote='La ricerca è completata e verificata.', **changes):
        fields = {'scope':'maverick', 'memory_type':'none', 'problem_kind':'capability_gap',
                  'generalization':'Enable reliable work with any workbook', 'verification':'Compare formulas before and after editing',
                  'evidence':[{'turn_id':'turn-1','role':'assistant','quote':quote}], **changes}
        return candidate(quote, **fields)

    def test_ongoing_episode_keeps_internal_context_without_publishing_candidates(self):
        self.capture(output_text='Sto ancora lavorando. Restano implementazione e test.')
        request = self.start(); data = json.loads(request['input_text'])
        output = analysis_output(data, improvements=[self.proposal(quote=data['exchanges'][0]['output_text'])])
        output['episode'].update(status='ongoing', summary='Implementation is underway', open_work=['Run tests'])
        self.finish(request, output)
        self.assertEqual(self.call()['items'], [])
        self.capture('turn-2')
        next_data = json.loads(self.start()['input_text'])
        self.assertEqual(next_data['episode_state']['open_work'], ['Run tests'])
        self.assertEqual(next_data['prior_context'][0]['turn_id'], 'turn-1')

    def test_completed_episode_cannot_have_open_work_or_failed_outcome(self):
        self.capture(); data = json.loads(self.start()['input_text'])
        output = analysis_output(data)
        output['episode']['open_work'] = ['Deploy the change']
        with self.assertRaises(ValueError):
            review_output(json.dumps(output), data)
        output['episode']['open_work'] = []
        data['exchanges'][0]['status'] = 'failed'
        with self.assertRaises(ValueError):
            review_output(json.dumps(output), data)

    def test_task_requests_and_already_handled_work_are_filtered(self):
        self.capture(); data = json.loads(self.start()['input_text'])
        for field, value in [('scope', 'task'), ('novelty', 'already_requested'), ('novelty', 'in_progress'),
                             ('novelty', 'resolved'), ('generalization', ''), ('verification', '')]:
            with self.subTest(field=field, value=value):
                proposal = {**self.proposal(), field: value}
                result = review_output(json.dumps(analysis_output(data, improvements=[proposal])), data)
                self.assertEqual(result['items'], [])
        self.assertEqual(len(review_output(json.dumps(analysis_output(data, improvements=[self.proposal()])), data)['items']), 1)

    def test_development_memory_is_filtered_even_if_mislabeled_as_preference(self):
        text = 'Voglio che cambi il toggle della interfaccia.'
        self.capture(input_text=text); data = json.loads(self.start()['input_text'])
        result = review_output(json.dumps(analysis_output(data, [candidate(text)])), data)
        self.assertEqual(result['items'], [])
        other = candidate(text, memory_type='development', scope='development')
        self.assertEqual(review_output(json.dumps(analysis_output(data, [other])), data)['items'], [])
        preference = candidate(text, body='Preferisco il toggle grande.')
        self.assertEqual(review_output(json.dumps(analysis_output(data, [preference])), data)['items'], [])

    def test_completed_sourced_assistant_research_is_eligible_but_bare_claim_is_not(self):
        text = 'Marco dirige Example, secondo https://example.com/team. Ricerca completata.'
        self.capture(output_text=text); data = json.loads(self.start()['input_text'])
        fact = candidate(body='Marco dirige Example.', memory_type='research', explicit=False,
            source_refs=['https://example.com/team'], evidence=[{'turn_id':'turn-1','role':'assistant','quote':text}])
        self.assertEqual(len(review_output(json.dumps(analysis_output(data, [fact])), data)['items']), 1)
        fact['source_refs'] = []
        self.assertEqual(review_output(json.dumps(analysis_output(data, [fact])), data)['items'], [])
        fact['source_refs'] = ['https://invented.example/team']
        with self.assertRaises(ValueError):
            review_output(json.dumps(analysis_output(data, [fact])), data)

    def test_publishing_is_fenced_when_new_completed_evidence_arrives_during_analysis(self):
        self.capture(); request = self.start(); data = json.loads(request['input_text'])
        self.capture('turn-2', output_text='La correzione è ancora in corso.')
        self.finish(request, analysis_output(data, improvements=[self.proposal()]))
        self.assertEqual(self.call()['items'], [])

    def test_new_user_turn_holds_queued_agent_until_reassessment_and_retires_duplicate(self):
        self.capture(); request = self.start(); data = json.loads(request['input_text'])
        self.finish(request, analysis_output(data, improvements=[self.proposal()]))
        item = self.call()['items'][0]
        self.call('learning.review', item_id=item['id'], command='accept')
        self.capture('turn-2', action='runtime.turn.queued', input_text='Implementa questa stessa correzione qui.')
        result = handle_learning({'data_root':self.root,'surface':'background_tick','body':{'action':'backend.tick','runtime_request_states':[]}})
        self.assertNotIn('runtime_session_requests', result)
        self.assertTrue(self.call()['items'][0]['details']['review_stale'])
        self.capture('turn-2', input_text='Implementa questa stessa correzione qui.', output_text='La correzione è completata e verificata.')
        request = self.start(); data = json.loads(request['input_text'])
        output = analysis_output(data, reconciliations=[{'item_id':item['id'],'disposition':'resolved',
            'reason':'Implemented in the source conversation','evidence':[{'turn_id':'turn-2','role':'assistant','quote':'La correzione è completata e verificata.'}]}])
        self.finish(request, output)
        self.assertEqual(self.call()['items'][0]['status'], 'rejected')
        self.assertEqual(self.call()['items'][0]['implementation']['status'], 'cancelled')

    def test_reconciliation_cannot_target_an_arbitrary_item(self):
        self.capture(); data = json.loads(self.start()['input_text'])
        output = analysis_output(data, reconciliations=[{'item_id':'invented','disposition':'resolved','reason':'Resolved',
            'evidence':[{'turn_id':'turn-1','role':'assistant','quote':'La ricerca è completata e verificata.'}]}])
        with self.assertRaises(ValueError):
            review_output(json.dumps(output), data)

    def test_cross_chat_active_requests_are_supplied_and_exclusions_respected(self):
        self.capture('other-turn', runtime_session_id='other', action='runtime.turn.queued', input_text='Sto implementando il supporto XLS.')
        self.capture(); data = json.loads(self.start()['input_text'])
        self.assertEqual(data['current_work'][0]['session_id'], 'other')
        self.assertIn('XLS', data['current_work'][0]['request'])

    def test_discard_all_fences_analysis_and_advances_cursor_without_recreating_backlog(self):
        self.capture(); first = self.start(); data = json.loads(first['input_text'])
        self.finish(first, analysis_output(data, improvements=[self.proposal()]))
        self.capture('turn-2'); running = self.start()
        result = self.call('learning.discard_all')
        self.assertEqual(result['discarded']['improvement'], 1)
        self.assertEqual(result['background_generation_cancel_requests'], [running['request_id']])
        self.assertEqual(self.finish(running, analysis_output(json.loads(running['input_text']))), {'ignored':True})
        self.assertNotIn('background_generation_requests', tick(self.root, {}))
        self.assertEqual(self.call()['items'][0]['status'], 'rejected')
        self.capture('turn-3'); next_data = json.loads(self.start()['input_text'])
        self.assertEqual([x['turn_id'] for x in next_data['exchanges']], ['turn-3'])
        self.assertTrue(next_data['existing_items'][0]['discarded_by_user'])

    def test_discard_all_requests_active_stop_and_is_idempotent_through_official_cli(self):
        self.capture(); request = self.start()
        self.finish(request, analysis_output(json.loads(request['input_text']), improvements=[self.proposal()]))
        item = self.call()['items'][0]
        with connection(self.root, write=True) as db:
            db.execute("INSERT INTO learning_implementations(item_id,status,actor,session_id,turn_id,created_at,updated_at) VALUES(?,'running','owner','work-chat','work-turn',?,?)", (item['id'], now(), now()))
        entry = Path(__file__).resolve().parents[1]/'cli'/'app_cli.py'
        payload = {'data_root':self.root,'workspace_role':'admin','user_id':'owner','arguments':{'action':'learning.discard_all'}}
        result = run_json_entrypoint(entry, payload=payload, cwd=entry.parent)
        self.assertEqual(result['status_code'], 200)
        self.assertEqual(result['runtime_turn_interrupt_requests'][0]['turn_id'], 'work-turn')
        self.assertEqual(self.call()['items'][0]['implementation']['status'], 'stopping')
        self.assertEqual(self.call('learning.discard_all')['discarded']['improvement'], 0)
        denied = run_json_entrypoint(entry, payload={**payload, 'workspace_role':'member'}, cwd=entry.parent)
        self.assertEqual(denied['status_code'], 403)

    def test_discarded_content_cannot_be_recreated_with_a_changed_model_key(self):
        self.capture(); request = self.start()
        self.finish(request, analysis_output(json.loads(request['input_text']), improvements=[self.proposal()]))
        self.call('learning.discard_all')
        self.capture('turn-2'); request = self.start()
        proposal = self.proposal(dedupe_key='A different key', evidence=[{'turn_id':'turn-2','role':'assistant','quote':'La ricerca è completata e verificata.'}])
        self.finish(request, analysis_output(json.loads(request['input_text']), improvements=[proposal]))
        self.assertEqual(len(self.call()['items']), 1)
        self.assertEqual(self.call()['items'][0]['status'], 'rejected')

    def test_episode_summary_and_context_remain_bounded_at_minimum_limit(self):
        self.call('learning.configure', settings={'max_context_chars':4000})
        self.capture()
        with connection(self.root, write=True) as db:
            db.execute('UPDATE learning_context SET episode_json=?', (json.dumps({'status':'ongoing','summary':'x'*2000,'open_work':['y'*500]*8}),))
        request = self.start()
        self.assertLessEqual(len(request['input_text']), 4000)
        self.assertTrue(json.loads(request['input_text'])['exchanges'])

    def test_excluded_project_proposals_are_not_exposed_to_other_reviews(self):
        self.capture(project_id='private'); request = self.start()
        self.finish(request, analysis_output(json.loads(request['input_text']), improvements=[self.proposal()]))
        self.call('learning.configure', settings={'excluded_project_ids':['private']})
        self.capture('turn-2', runtime_session_id='public')
        self.assertEqual(json.loads(self.start()['input_text'])['existing_items'], [])

    def test_memory_agent_cannot_commit_after_its_source_changes(self):
        text = 'Marco vive a Milano da dieci anni.'
        self.capture(input_text=text); request = self.start()
        self.finish(request, analysis_output(json.loads(request['input_text']), [candidate(text, memory_type='person')]))
        item = self.call()['items'][0]
        with connection(self.root, write=True) as db:
            db.execute("UPDATE learning_items SET status='accepted' WHERE id=?", (item['id'],))
            db.execute("INSERT INTO learning_implementations(item_id,status,actor,session_id,turn_id,created_at,updated_at) VALUES(?,'running','owner','work-chat','work-turn',?,?)", (item['id'], now(), now()))
        self.capture('turn-2', action='runtime.turn.queued', input_text='Correzione: Marco si è trasferito.')
        with self.assertRaisesRegex(ValueError, 'source conversation changed'):
            handle_learning({'data_root':self.root,'surface':'mcp','runtime_session_id':'work-chat',
                             'body':{'action':'learning.memory_agent','item_id':item['id'],'command':'commit'}})


if __name__ == '__main__':
    unittest.main()
