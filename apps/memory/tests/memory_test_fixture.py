"""Isolated Memory action fixtures shared by reviewer regression suites."""

import importlib
from pathlib import Path
import sys
import tempfile
import unittest

from test_memory_app import evict_foreign_backend_modules


class MemoryTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'data' / 'memory'
        evict_foreign_backend_modules()
        backend = str(Path(__file__).resolve().parents[1] / 'backend')
        sys.path.insert(0, backend)
        self.addCleanup(sys.path.remove, backend)
        self.service = importlib.import_module('service')
        self.database = importlib.import_module('database')

    def call(self, action, **values):
        status, result = self.service.handle_action(self.root, {'action': action, **values})
        self.assertEqual(status, 200, result)
        return result

    def remote(self, **values):
        request = {
            'title': 'Remote contract', 'preview_text': 'Il contratto annuale costa 1200 euro.',
            'memory_source': {
                'source_kind': 'remote_storage_file', 'owning_app_id': 'storage',
                'entity_type': 'file', 'entity_id': 'file_drive_contract',
                'file_id': 'file_drive_contract', 'metadata': {
                    'provider': 'google_drive', 'connection_id': 'drive_connection',
                    'drive_file_id': 'drive_contract', 'source_version': 'rev-1',
                    'display_path': '/Drive/Contract.md',
                },
            },
        }
        return self.call('ingest_storage_source', **{**request, **values})
