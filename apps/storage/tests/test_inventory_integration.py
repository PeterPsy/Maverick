"""Storage indexed API and interrupted filesystem commits through public operations."""

import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import inventory
import inventory_legacy
from inventory_migration import cutover_inventory, prepare_inventory, rollback_inventory
from inventory_operations import mutate, recover_operations
from inventory_reconcile import reconcile_inventory
from inventory_sqlite import InventoryIndex


@unittest.skipIf(sqlite3.sqlite_version_info < (3, 51, 3), 'Run with the verified WAL-safe runtime')
class IndexedStorageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        base = Path(self.scratch.name)
        self.data = base / 'data'
        self.roots = {role: base / role for role in ('uploaded', 'generated')}
        for root in self.roots.values():
            root.mkdir()
        self.root = self.roots['generated']
        (self.root / 'first.md').write_text('first')
        self.arguments = {'uploaded_root': self.roots['uploaded'], 'generated_root': self.root}
        inventory_legacy.sync_inventory(self.data, **self.arguments)
        migration = prepare_inventory(self.data, **self.arguments)
        cutover_inventory(self.data, migration['migration_id'], **self.arguments)
        self.index = InventoryIndex(self.data)

    def catalog(self, **filters):
        return inventory.catalog_inventory_payload(data_root=self.data, **self.arguments, **filters)

    def write(self, name, payload):
        return mutate(data_root=self.data, role='generated', root=self.root,
            target=self.root / name, kind='write', payload=payload)

    def test_read_and_resolve_do_not_stat_or_rewrite_metadata(self):
        page = self.catalog()
        source = (self.data / 'files.json').read_bytes()
        revision = page['dataset_revision']
        with patch.object(Path, 'stat', side_effect=AssertionError('filesystem read')), patch('os.scandir', side_effect=AssertionError('scan')):
            self.assertEqual(self.catalog()['dataset_revision'], revision)
            resolved = inventory.resolve_file_record(data_root=self.data, **self.arguments, entity_id=page['files'][0]['id'])
            self.assertEqual(resolved['name'], 'first.md')
            self.assertIsNone(inventory.resolve_file_record(data_root=self.data, **self.arguments, entity_id='generated:unseen.md'))
        self.assertEqual((self.data / 'files.json').read_bytes(), source)

    def test_indexed_quota_does_not_scan_the_storage_tree(self):
        from store_files_paths import enforce_storage_budget
        from errors import StorageValidationError
        with patch.dict(os.environ, {'MAVERICK_STORAGE_MAX_BYTES': '10'}), \
             patch.object(Path, 'rglob', side_effect=AssertionError('quota tree scan')):
            enforce_storage_budget(data_root=self.data, **self.arguments, target=self.root / 'second.md', payload_size=5)
            with self.assertRaisesRegex(StorageValidationError, 'quota_exceeded'):
                enforce_storage_budget(data_root=self.data, **self.arguments, target=self.root / 'second.md', payload_size=6)
            enforce_storage_budget(data_root=self.data, **self.arguments, target=self.root / 'first.md', payload_size=10)

    def test_upsert_unchanged_preserves_revision_hash_and_memory(self):
        file = self.write('first.md', b'first')
        with self.index.transaction(write=True) as connection:
            raw = self.index.get(connection, file['id'])
            raw.update(memory_node_id='node-1', indexed=True, index_status='indexed')
            self.index.put_file(connection, raw)
        before = self.catalog()['dataset_revision']
        record = inventory.upsert_file_record(data_root=self.data, role='generated', root=self.root, path=self.root / 'first.md')
        self.assertEqual(self.catalog()['dataset_revision'], before)
        self.assertEqual(record['sha256'], file['sha256'])
        self.assertEqual(record['memory_node_id'], 'node-1')

    def test_same_size_and_restored_mtime_invalidates_hash(self):
        first = self.write('first.md', b'first')
        path = self.root / 'first.md'
        old = path.stat()
        path.write_bytes(b'other')
        os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
        updated = inventory.upsert_file_record(data_root=self.data, role='generated', root=self.root, path=path)
        self.assertEqual(updated['id'], first['id'])
        self.assertEqual(updated['sha256'], '')

    def test_crash_after_filesystem_write_recovers_reserved_identity(self):
        with patch('inventory_operations._finalize', side_effect=OSError('crash')):
            with self.assertRaises(OSError):
                self.write('new.md', b'new file')
        with self.index.transaction() as connection:
            pending = json.loads(connection.execute('SELECT document FROM operations').fetchone()[0])
        recover_operations(self.data, self.roots)
        file = inventory.resolve_file_record(data_root=self.data, **self.arguments, entity_id='generated:new.md')
        self.assertEqual(file['id'], pending['file_id'])
        self.assertEqual((self.root / 'new.md').read_bytes(), b'new file')
        self.assertEqual(recover_operations(self.data, self.roots)['recovered'], 0)

    def test_crash_before_replace_finishes_durably_prepared_bytes(self):
        previous = self.write('first.md', b'first')
        with patch.object(Path, 'replace', side_effect=OSError('crash')):
            with self.assertRaises(OSError):
                self.write('first.md', b'changed')
        recover_operations(self.data, self.roots)
        self.assertEqual((self.root / 'first.md').read_bytes(), b'changed')
        self.assertEqual(self.catalog()['files'][0]['id'], previous['id'])

    def test_move_then_delete_subtree_and_reverse_export(self):
        folder = self.root / 'folder'
        mutate(data_root=self.data, role='generated', root=self.root, target=folder, kind='create_directory')
        first = self.write('folder/child.md', b'child')
        new = self.root / 'renamed'
        mutate(data_root=self.data, role='generated', root=self.root, target=new, source=folder, kind='move_directory')
        record = inventory.resolve_file_record(data_root=self.data, **self.arguments, entity_id=first['id'])
        self.assertEqual(record['relative_path'], 'renamed/child.md')
        self.assertEqual(record['sha256'], first['sha256'])
        mutate(data_root=self.data, role='generated', root=self.root, target=new, kind='delete_directory')
        self.assertIsNone(inventory.resolve_file_record(data_root=self.data, **self.arguments, entity_id=first['id']))
        rollback_inventory(self.data)
        exported = json.loads((self.data / 'files.json').read_text())
        self.assertEqual(next(row for row in exported['files'] if row['id'] == first['id'])['status'], 'deleted')

    def test_resumable_discovery_and_deletion_wait_for_complete_scan(self):
        for number in range(90):
            (self.root / f'external-{number}.md').write_text(str(number))
        (self.root / 'first.md').unlink()
        first = reconcile_inventory(self.data, **self.arguments, max_stats=12, max_seconds=1)
        self.assertLessEqual(first['inspected'], 12)
        self.assertTrue(any(file['name'] == 'first.md' for file in self.catalog(limit=200)['files']))
        for _ in range(20):
            reconcile_inventory(self.data, **self.arguments, max_stats=12, max_seconds=1)
        page = self.catalog(limit=200)
        self.assertEqual(page['pagination']['total'], 90)
        self.assertFalse(any(file['name'] == 'first.md' for file in page['files']))

    def test_io_failure_does_not_tombstone_any_files(self):
        before = self.catalog()
        with patch('os.scandir', side_effect=PermissionError('no access')):
            result = reconcile_inventory(self.data, **self.arguments)
        self.assertEqual(result['status'], 'retrying')
        self.assertEqual(self.catalog()['files'], before['files'])

    def test_one_pass_reuses_directory_handles_and_reschedules_backlog(self):
        for number in range(600):
            (self.root / f'external-{number}.md').write_text(str(number))
        with patch('os.scandir', wraps=os.scandir) as scandir:
            result = reconcile_inventory(self.data, **self.arguments, max_stats=2000, max_seconds=10)
        self.assertEqual(self.catalog()['pagination']['total'], 601)
        self.assertLessEqual(scandir.call_count, 2)
        self.assertEqual(result['next_due_in_seconds'], 15)
        with self.index.transaction(write=True) as connection:
            connection.execute('UPDATE scan_queue SET last_completed=0')
        result = reconcile_inventory(self.data, **self.arguments, max_stats=12, max_seconds=1)
        self.assertEqual(result['next_due_in_seconds'], 1)

    def test_external_subtree_deletion_finishes_in_bounded_batches(self):
        import shutil
        folder = self.root / 'removed'
        folder.mkdir()
        for number in range(180):
            (folder / f'child-{number}.md').write_text('child')
        reconcile_inventory(self.data, **self.arguments, max_seconds=10)
        shutil.rmtree(folder)
        with self.index.transaction(write=True) as connection:
            connection.execute('UPDATE scan_queue SET last_completed=0')
        for _ in range(10):
            reconcile_inventory(self.data, **self.arguments, max_stats=12, max_seconds=1)
        self.assertEqual(self.catalog()['pagination']['total'], 1)
        with self.index.transaction() as connection:
            self.assertIsNone(connection.execute("SELECT 1 FROM scan_queue WHERE path='removed'").fetchone())


if __name__ == '__main__':
    unittest.main()
