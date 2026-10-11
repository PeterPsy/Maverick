"""Chat's real save request verifies evidence independently of source locators."""

from pathlib import Path
import unittest

from core.shared.entrypoints import run_json_entrypoint
from test_learning_regressions import LearningTestCase
from test_conversation_learning import candidate
from learning_memory import memory_callback, save_request
from learning_store import connection


class LearningMemoryEvidenceTests(LearningTestCase):
    def test_save_request_with_uuid_and_file_locator_preserves_verified_citations(self):
        fact = 'Marco vive a Milano da dieci anni'
        memory_app = Path(__file__).resolve().parents[2] / 'memory'
        cases = [('source', []), ('123e4567-e89b-12d3-a456-426614174000', []),
            ('6ffac360-5834-44c8-ae44-97c90ed37896', ['https://example.com/contract-2026-a.pdf'])]
        for index, (session, source_refs) in enumerate(cases):
            with self.subTest(session=session, source_refs=source_refs):
                self.root = str(Path(self.temp.name) / f'chat-{index}')
                self.call('learning.configure', settings={'enabled': True, 'idle_seconds': 0})
                self.capture(session=session, input_text='\n'.join([fact, *source_refs]))
                check = self.finish(self.start(), memory=[candidate(fact, memory_type='person',
                    source_refs=source_refs)])['dependency_backend_requests'][0]
                memory_callback(self.root, {**check['callback']['payload'], 'action': 'learning.memory_checked',
                    'dependency_backend_status': 'completed', 'dependency_backend_result': {
                        'status_code': 200, 'dependency_provider_app_id': 'memory', 'json': {'results': []}}})
                with connection(self.root, write=True) as db:
                    item = db.execute('SELECT * FROM learning_items WHERE id=?',
                        (check['callback']['payload']['item_id'],)).fetchone()
                    request = save_request(db, item, actor='user')
                self.assertIn(session, request['body']['body_markdown'])
                result = run_json_entrypoint(memory_app / 'backend' / 'app_backend.py', payload={
                    'data_root': str(Path(self.temp.name) / f'memory-{index}'), 'app_id': 'memory',
                    'surface': 'backend', 'body': request['body']}, cwd=memory_app)
                self.assertEqual(result['status_code'], 200, result)
                saved = result['json']
                self.assertEqual(saved['node']['body_text'], fact)
                self.assertEqual(saved['compiled']['compiled_page']['verification'], 'verified')
                self.assertEqual([citation['quote'] for citation in saved['compiled']['citations']], [fact])
                memory_callback(self.root, {**request['callback']['payload'], 'action': 'learning.memory_saved',
                    'dependency_backend_status': 'completed', 'dependency_backend_result': {
                        **result, 'dependency_provider_app_id': 'memory'}})
                item = self.call()['items'][0]
                self.assertEqual(item['status'], 'saved')
                self.assertTrue(item['details']['saved_fact_verified'])


if __name__ == '__main__':
    unittest.main()
