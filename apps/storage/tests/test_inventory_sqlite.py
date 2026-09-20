"""Storage index invariants without app/bootstrap or filesystem scan dependencies."""

from __future__ import annotations

from copy import deepcopy
from contextlib import closing
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from inventory_queries import catalog_page, directory_page, reference_records, summary_payload
from errors import StorageConflictError
from inventory_sqlite import InventoryIndex, natural_key


def record(index: int, *, name: str | None = None) -> dict:
    name = name or f'file{index}.md'
    return {'file_id': f'file_{index:032x}', 'id': f'file_{index:032x}',
        'role': 'generated', 'provider': 'local', 'connection_id': '', 'drive_file_id': '',
        'relative_path': name, 'workspace_relative_path': f'storage/generated/{name}',
        'name': name, 'size_bytes': index + 1, 'status': 'active', 'preview_kind': 'markdown',
        'extension': '.md', 'created_at': '2026-09-01T00:00:00+00:00',
        'modified_at': '2026-09-01T00:00:00+00:00', 'updated_at': '2026-09-01T00:00:00+00:00',
        'remote_locator': {}, 'memory_node_id': f'memory-{index}', 'sha256': 'a' * 64}


def _concurrent_writer(root: str, offset: int):
    index = InventoryIndex(Path(root))
    for number in range(offset, offset + 20):
        with index.transaction(write=True) as connection:
            index.put_file(connection, record(number))


def _crash_before_commit(root: str):
    index = InventoryIndex(Path(root))
    with index.transaction(write=True) as connection:
        index.put_file(connection, record(800))
        os._exit(7)


@unittest.skipIf(sqlite3.sqlite_version_info < (3, 51, 3), 'Run with the verified WAL-safe runtime')
class InventoryIndexTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.index = InventoryIndex(Path(self.scratch.name))
        self.index.initialize()
        with self.index.transaction(write=True) as connection:
            for index in range(250):
                self.index.put_file(connection, record(index))

    def test_catalog_reads_do_not_touch_filesystem_or_write(self):
        with self.index.transaction() as connection:
            revision = self.index.revision(connection)
        with patch.object(Path, 'stat', side_effect=AssertionError('catalog stat')), patch('os.scandir', side_effect=AssertionError('catalog scan')):
            page = catalog_page(self.index, role='generated', limit=100, sort_by='size_bytes')
            next_page = catalog_page(self.index, role='generated', limit=100, offset=100,
                sort_by='size_bytes', dataset_revision=page['dataset_revision'])
        self.assertEqual(page['files'][0]['size_bytes'], 250)
        self.assertEqual(next_page['files'][0]['size_bytes'], 150)
        self.assertEqual(page['totals'], {'scope': 'filtered', 'total_files': 250, 'total_bytes': 31375})
        self.assertEqual(page['dataset_revision'], revision)
        self.assertEqual(next_page['dataset_revision'], revision)
        self.assertEqual(page['files'][0]['memory_node_id'], 'memory-249')

    def test_changed_revision_never_returns_a_page_to_append(self):
        page = catalog_page(self.index, limit=100)
        with self.index.transaction(write=True) as connection:
            self.index.put_file(connection, record(300))
        next_page = catalog_page(self.index, offset=100, dataset_revision=page['dataset_revision'])
        self.assertEqual(next_page['status'], 'catalog_changed')
        self.assertNotIn('files', next_page)

    def test_other_folder_writes_do_not_starve_a_stable_catalog_page(self):
        with self.index.transaction(write=True) as connection:
            for number in range(300, 303):
                self.index.put_file(connection, record(number, name=f'reading/file{number}.md'))
        first = catalog_page(self.index, role='generated', folder_path='reading', limit=1,
            sort_by='name', sort_direction='asc')
        for number in range(400, 404):
            with self.index.transaction(write=True) as connection:
                self.index.put_file(connection, record(number, name=f'uploads/file{number}.md'))
            following = catalog_page(self.index, role='generated', folder_path='reading', limit=1,
                offset=1, sort_by='name', sort_direction='asc', dataset_revision=first['dataset_revision'])
            self.assertEqual(following['status'], 'ok')
            self.assertEqual(following['files'][0]['file_id'], record(301)['file_id'])
        with self.index.transaction(write=True) as connection:
            self.index.put_file(connection, {**record(301, name='reading/file301.md'), 'status': 'deleted'})
        self.assertEqual(catalog_page(self.index, role='generated', folder_path='reading', limit=1,
            offset=1, dataset_revision=first['dataset_revision'])['status'], 'catalog_changed')

    def test_existing_untracked_scopes_remain_read_only_and_moves_invalidate_both_folders(self):
        with self.index.transaction(write=True) as connection:
            self.index.put_file(connection, record(300, name='reading/file300.md'))
            connection.execute("DELETE FROM metadata WHERE key LIKE 'view_revision:%'")
        first = catalog_page(self.index, role='generated', folder_path='reading')
        other = catalog_page(self.index, role='generated', folder_path='archive')
        self.assertEqual(first['dataset_revision'], 0)
        with self.index.transaction() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM metadata WHERE key LIKE 'view_revision:%'").fetchone()[0], 0)
        with self.index.transaction(write=True) as connection:
            self.index.put_file(connection, record(300, name='archive/file300.md'))
        for folder, page in [('reading', first), ('archive', other)]:
            self.assertEqual(catalog_page(self.index, role='generated', folder_path=folder,
                dataset_revision=page['dataset_revision'])['status'], 'catalog_changed')
        with self.index.transaction() as connection:
            from inventory_revisions import view_revision
            self.assertEqual(view_revision(connection, role='generated', parent=''), self.index.revision(connection))
            self.assertEqual(view_revision(connection, role='uploaded'), 0)

    def test_unchanged_write_does_not_change_revision_or_totals(self):
        before = summary_payload(self.index)
        with self.index.transaction(write=True) as connection:
            self.assertFalse(self.index.put_file(connection, record(1)))
        self.assertEqual(summary_payload(self.index), before)

    def test_path_conflict_rolls_back_and_tombstone_preserves_identity(self):
        before = summary_payload(self.index)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.index.transaction(write=True) as connection:
                self.index.put_file(connection, record(900, name='file1.md'))
        self.assertEqual(summary_payload(self.index), before)
        with self.index.transaction(write=True) as connection:
            original = record(1)
            self.index.put_file(connection, {**original, 'status': 'deleted'})
            replacement = record(900, name='file1.md')
            self.index.put_file(connection, replacement)
            self.assertEqual(self.index.get(connection, original['file_id'])['status'], 'deleted')
            self.assertEqual(self.index.by_path(connection, 'generated', 'file1.md')['file_id'], replacement['file_id'])

    def test_filter_and_custom_order_precede_limit(self):
        ids = [record(index)['file_id'] for index in (200, 3, 100)]
        page = catalog_page(self.index, file_ids=ids, limit=2)
        self.assertEqual([item['file_id'] for item in page['files']], ids[:2])
        self.assertEqual(page['totals']['total_files'], 3)
        matching = catalog_page(self.index, query='file24', limit=2, sort_by='name', sort_direction='asc')
        self.assertEqual([item['name'] for item in matching['files']], ['file24.md', 'file240.md'])
        self.assertEqual(matching['pagination']['total'], 11)

    def test_backup_contains_remote_metadata_and_empty_directories(self):
        remote = deepcopy(record(999))
        remote.update(provider='google_drive', connection_id='drive-a', drive_file_id='remote-a',
            remote_locator={'parent_ids': ['parent'], 'drive_id': 'shared'}, status='deleted')
        directory = {'id': 'generated:empty/', 'role': 'generated', 'relative_path': 'empty',
            'status': 'active', 'name': 'empty'}
        with self.index.transaction(write=True) as connection:
            self.index.put_file(connection, remote)
            self.index.put_directory(connection, directory)
        destination = Path(self.scratch.name) / 'backup.sqlite'
        self.index.backup(destination)
        with closing(sqlite3.connect(destination)) as connection:
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(json.loads(connection.execute('SELECT document FROM files WHERE file_id=?', (remote['file_id'],)).fetchone()[0]), remote)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM directories').fetchone()[0], 1)

    def test_two_process_writers_and_reader_preserve_all_records(self):
        context = multiprocessing.get_context('fork')
        writers = [context.Process(target=_concurrent_writer, args=(self.scratch.name, offset)) for offset in (300, 400)]
        for writer in writers:
            writer.start()
        for _ in range(20):
            page = catalog_page(self.index, limit=100)
            self.assertEqual(len({item['file_id'] for item in page['files']}), 100)
            self.assertGreaterEqual(page['totals']['total_files'], 250)
        for writer in writers:
            writer.join(timeout=10)
            self.assertFalse(writer.is_alive())
            self.assertEqual(writer.exitcode, 0)
        self.assertEqual(catalog_page(self.index)['totals']['total_files'], 290)

    def test_process_crash_before_commit_cannot_publish_partial_totals(self):
        before = summary_payload(self.index)
        process = multiprocessing.get_context('fork').Process(target=_crash_before_commit, args=(self.scratch.name,))
        process.start()
        process.join(timeout=10)
        self.assertEqual(process.exitcode, 7)
        self.assertEqual(summary_payload(self.index), before)

    def test_unknown_schema_is_refused_without_fallback(self):
        with self.index.connect(write=True) as connection:
            connection.execute('PRAGMA user_version=999')
        with self.assertRaisesRegex(RuntimeError, 'explicit migration'):
            catalog_page(self.index)

    def test_directories_search_page_exact_totals_and_hidden_upload_buckets(self):
        with self.index.transaction(write=True) as connection:
            for number in range(250):
                self.index.put_directory(connection, {'id': f'generated:folder{number}/',
                    'role': 'generated', 'relative_path': f'folder{number}', 'name': f'folder{number}', 'status': 'active'})
            bucket = '12345678-1234-1234-1234-123456789abc'
            self.index.put_directory(connection, {'id': f'uploaded:{bucket}/',
                'role': 'uploaded', 'relative_path': bucket, 'name': bucket, 'status': 'active'})
        page = catalog_page(self.index, role='generated', folder_path='', limit=100)
        self.assertEqual(page['folders_pagination']['total'], 250)
        self.assertEqual(page['folders'][-1]['name'], 'folder99')
        with self.index.transaction() as connection:
            next_page = directory_page(connection, role='generated', parent='', offset=100, limit=100)
            self.assertEqual(next_page['folders'][0]['name'], 'folder100')
            search = directory_page(connection, role='all', parent='', query='ＦＯＬＤＥＲ２４')
            self.assertEqual(search['pagination']['total'], 11)
            self.assertEqual(directory_page(connection, role='uploaded', parent='')['pagination']['total'], 0)
        self.assertEqual(summary_payload(self.index)['containers'][0]['total_folders'], 0)

    def test_pending_mutation_fences_all_indexed_read_models(self):
        with self.index.transaction(write=True) as connection:
            connection.execute("INSERT INTO operations VALUES ('pending','{}')")
        for read in (lambda: catalog_page(self.index), lambda: summary_payload(self.index),
                     lambda: reference_records(self.index, query='', folder=True, limit=10)):
            with self.assertRaises(StorageConflictError):
                read()
        with self.index.transaction() as connection, self.assertRaises(StorageConflictError):
            directory_page(connection, role='all', parent='')


class NaturalOrderTests(unittest.TestCase):
    def test_numbers_case_unicode_and_leading_zeroes(self):
        self.assertLess(natural_key('File2'), natural_key('file10'))
        self.assertEqual(natural_key('FILE02'), natural_key('file2'))
        self.assertEqual(natural_key('Ａ２'), natural_key('a2'))
        self.assertEqual(natural_key('É'), natural_key('E\u0301'))
        self.assertLess(natural_key('f' + '9' * 100), natural_key('f1' + '0' * 100))
