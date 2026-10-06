"""Learning uses source idempotence and guarded undo through Memory's backend."""
from pathlib import Path
import tempfile
import unittest

from core.shared.entrypoints import run_json_entrypoint


class LearningSourceIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.app=Path(__file__).resolve().parents[1]

    def call(self,body,surface='backend'):
        return run_json_entrypoint(self.app/'backend/app_backend.py',payload={'data_root':str(self.root),'app_id':'memory','surface':surface,'body':body},cwd=self.app)

    def ingest(self):
        return self.call({'action':'ingest_source','adapter_id':'inline_markdown','source_key':'conversation-learning:fixture','title':'Preference',
            'summary':'Prefer short replies','node_type':'fact','body_markdown':'User: Prefer short replies.','compile_after_ingest':True})

    def test_repeated_source_ingest_creates_one_node_and_undo_is_guarded(self):
        initial=self.ingest()
        self.assertEqual(initial['status_code'],200,initial)
        replay=self.ingest()
        self.assertEqual(replay['json']['node']['id'],initial['json']['node']['id'])
        self.assertFalse(replay['json']['node_created'])
        node=replay['json']['node']
        old_revision=node['updated_at']
        updated=self.call({'action':'update_node','node_id':node['id'],'title':'User-edited preference'})
        self.assertEqual(updated['status_code'],200,updated)
        rejected=self.call({'action':'delete_node','node_id':node['id'],'expected_updated_at':old_revision,'reason':'conversation_learning_undo'})
        self.assertEqual(rejected['status_code'],400,rejected)
        current=self.call({'action':'inspect','node_id':node['id']})['json']['node']
        deletion={'action':'delete_node','node_id':node['id'],'expected_updated_at':current['updated_at'],'reason':'conversation_learning_undo'}
        self.assertEqual(self.call(deletion)['status_code'],200)
        self.assertEqual(self.call(deletion)['status_code'],200)

    def test_secret_preflight_does_not_execute_write(self):
        result=self.call({'action':'delete_node','node_id':'missing'},surface='secret_selector')
        self.assertEqual(result['secret_requests'],[])
        self.assertFalse((self.root/'memory.sqlite').exists())
