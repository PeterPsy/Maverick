"""Lossless explicit cutovers with source/fingerprint fences and post-cutover rollback."""

import json
import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from inventory_migration import cutover_inventory, prepare_inventory, rollback_inventory
from inventory_sqlite import InventoryIndex


@unittest.skipIf(sqlite3.sqlite_version_info < (3, 51, 3), 'Run with the verified WAL-safe runtime')
class InventoryMigrationTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.roots = {'uploaded_root': self.root / 'uploaded', 'generated_root': self.root / 'generated'}
        for root in self.roots.values():
            root.mkdir()
        self.file = self.roots['generated_root'] / 'report.md'
        self.file.write_text('fixture')
        self.record = {'file_id': 'file_' + '1' * 32, 'id': 'file_' + '1' * 32, 'provider': 'local',
            'connection_id': '', 'drive_file_id': '', 'role': 'generated', 'relative_path': 'report.md',
            'name': 'report.md', 'status': 'active', 'preview_kind': 'markdown', 'size_bytes': 7,
            'extension': '.md', 'sha256': hashlib.sha256(b'fixture').hexdigest(), 'created_at': '2026-09-01T00:00:00+00:00',
            'memory_node_id': 'memory-1', 'remote_locator': {}, 'capabilities': {'can_read': True}}
        self.payload = {'schema_version': '1', 'files': [self.record], 'directories': [], 'updated_at': 'preserve'}
        self.source = self.data / 'files.json'
        self.source.write_text(json.dumps(self.payload))

    def test_prepare_is_read_only_then_cutover_and_rollback_keep_new_identity(self):
        source = self.source.read_bytes()
        prepared = prepare_inventory(self.data, **self.roots)
        self.assertEqual(self.source.read_bytes(), source)
        self.assertFalse((self.data / 'inventory.sqlite').exists())
        cutover_inventory(self.data, prepared['migration_id'], **self.roots)
        index = InventoryIndex(self.data)
        new = {**self.record, 'file_id': 'file_' + '2' * 32, 'id': 'file_' + '2' * 32,
            'name': 'new.md', 'relative_path': 'new.md', 'memory_node_id': 'memory-new'}
        with index.transaction(write=True) as connection:
            index.put_file(connection, new)
            index.put_file(connection, {**self.record, 'status': 'deleted', 'deleted_at': 'after-cutover'})
        rollback_inventory(self.data)
        restored = json.loads(self.source.read_text())
        self.assertEqual(len(restored['files']), 2)
        self.assertEqual(restored['files'][0]['status'], 'deleted')
        self.assertEqual(restored['files'][1], new)
        self.assertFalse((self.data / 'inventory.sqlite').exists())
        self.assertEqual(json.loads((self.data / 'inventory-store.json').read_text())['adapter'], 'json')

    def test_same_size_external_change_invalidates_preparation(self):
        prepared = prepare_inventory(self.data, **self.roots)
        self.file.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'changed after preparation'):
            cutover_inventory(self.data, prepared['migration_id'], **self.roots)
        self.assertFalse((self.data / 'inventory-store.json').exists())

    def test_new_external_file_invalidates_preparation(self):
        prepared = prepare_inventory(self.data, **self.roots)
        (self.roots['generated_root'] / 'external.md').write_text('new')
        with self.assertRaisesRegex(ValueError, 'changed after preparation'):
            cutover_inventory(self.data, prepared['migration_id'], **self.roots)

    def test_duplicate_identity_and_active_paths_are_rejected(self):
        self.payload['files'].append(dict(self.record))
        self.source.write_text(json.dumps(self.payload))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            prepare_inventory(self.data, **self.roots)
        self.payload['files'][1]['file_id'] = 'file_' + '2' * 32
        self.source.write_text(json.dumps(self.payload))
        with self.assertRaises(sqlite3.IntegrityError):
            prepare_inventory(self.data, **self.roots)

    def test_cutover_retries_a_completed_promotion_without_replacing_data(self):
        prepared = prepare_inventory(self.data, **self.roots)
        with patch('inventory_migration._write_json', side_effect=OSError('marker write interrupted')):
            with self.assertRaises(OSError):
                cutover_inventory(self.data, prepared['migration_id'], **self.roots)
        self.assertTrue((self.data / 'inventory.sqlite').exists())
        result = cutover_inventory(self.data, prepared['migration_id'], **self.roots)
        self.assertEqual(result['status'], 'active')

    def test_rollback_retry_never_overwrites_subsequent_json_writes(self):
        prepared = prepare_inventory(self.data, **self.roots)
        cutover_inventory(self.data, prepared['migration_id'], **self.roots)
        rollback_inventory(self.data)
        newer = json.loads(self.source.read_text())
        newer['updated_at'] = 'new-write-after-rollback'
        self.source.write_text(json.dumps(newer))
        rollback_inventory(self.data)
        self.assertEqual(json.loads(self.source.read_text()), newer)

    def test_stale_content_hash_is_rejected_before_becoming_authoritative(self):
        self.file.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'content hash is stale'):
            prepare_inventory(self.data, **self.roots)
