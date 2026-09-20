"""Usage handoff preserves identities and rejects stale writers on both sides."""

from contextlib import closing
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.control_store import ControlStoreSettings, build_control_plane_collections, control_plane_collection_specs
from core.api.persistence_admin import _copy_collections
from core.api.persistence_cleanup_worker import _clear_source_storage
from core.shared.json_file_collection import JsonFileCollection
from core.usage.bootstrap import build_usage_store
from core.usage.handoff import USAGE_ROOT, active_adapter, usage_fence
from core.usage import migration
from core.usage.service import ingest_runtime_usage
from core.usage.sqlite_store import UsageSqliteStore
from core.usage.store import UsageCollections
from tests.unit.usage.test_usage_service import _RuntimeStore, _session


@unittest.skipIf(sqlite3.sqlite_version_info < (3, 51, 3), 'Requires the verified WAL-safe runtime')
class UsageMigrationTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.env = patch.dict(os.environ, {'MAVERICK_USAGE_STORE': 'document'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.collections = UsageCollections(*(JsonFileCollection(self.root / "json" / (name + ".json"))
            for name in ("samples", "buckets", "quotas")))
        self.document = build_usage_store(self.root, self.collections)
        self.session = _session('root')
        self.state = SimpleNamespace(usage_store=self.document, runtime_store=_RuntimeStore(self.session), provider_registry=None)
        self.ingest('one', 100)

    def ingest(self, identity, total):
        return ingest_runtime_usage(self.state, session_id='root', turn_id='turn',
            observed_at=datetime(2026, 9, 20, 10, tzinfo=UTC), payload={
                'usage_id': identity, 'semantics': 'incremental', 'input_tokens': total, 'total_tokens': total})

    def cutover(self):
        prepared = migration.prepare(self.root, self.collections)
        migration.validate(self.root, prepared['migration_id'])
        migration.cutover(self.root, self.collections, prepared['migration_id'])
        os.environ['MAVERICK_USAGE_STORE'] = 'sqlite'
        self.state.usage_store = build_usage_store(self.root, self.collections)
        return prepared

    def test_explicit_handoff_backup_and_reverse_export_include_new_writes(self):
        before = self.document.list_samples()
        prepared = self.cutover()
        self.assertEqual(self.state.usage_store.list_samples(), before)
        self.assertEqual(migration.cutover(self.root, self.collections, prepared['migration_id'])['status'], 'already_active')
        with self.assertRaisesRegex(RuntimeError, 'adapter changed'):
            self.document.delete_sessions(['root'])
        self.ingest('two', 200)
        backup = migration.backup(self.root)
        self.assertEqual(backup['counts']['samples'], 2)
        archived = UsageSqliteStore(self.root / backup['path'] / 'usage.sqlite')
        self.assertEqual(archived.list_samples(), self.state.usage_store.list_samples())
        sql_store = self.state.usage_store
        migration.rollback(self.root, self.collections)
        with self.assertRaisesRegex(RuntimeError, 'adapter changed'):
            sql_store.delete_sessions(['root'])
        os.environ['MAVERICK_USAGE_STORE'] = 'document'
        self.state.usage_store = build_usage_store(self.root, self.collections)
        self.assertEqual(self.ingest('three', 300).summary.tokens.total_tokens, 600)
        migration.rollback(self.root, self.collections)
        self.assertEqual(len(self.state.usage_store.list_samples()), 3)
        self.cutover()
        self.assertEqual(len(self.state.usage_store.list_samples()), 3)

    def test_prepare_rejects_source_change_and_tampered_staging(self):
        prepared = migration.prepare(self.root, self.collections)
        self.ingest('two', 200)
        with self.assertRaisesRegex(RuntimeError, 'source changed'):
            migration.cutover(self.root, self.collections, prepared['migration_id'])
        prepared = migration.prepare(self.root, self.collections)
        staged = UsageSqliteStore(self.root / USAGE_ROOT / 'migrations' / prepared['migration_id'] / 'usage.sqlite')
        with staged.transaction(write=True) as connection:
            connection.execute('UPDATE session_totals SET total_tokens=0')
        with self.assertRaisesRegex(RuntimeError, 'projection'):
            migration.validate(self.root, prepared['migration_id'])
        self.assertEqual(active_adapter(self.root / USAGE_ROOT), 'document')

    def test_cutover_retry_after_promotion_and_rollback_retry_after_marker(self):
        prepared = migration.prepare(self.root, self.collections)
        original = migration.atomic_json
        def fail_marker(path, value):
            if path.name == 'store.json':
                raise OSError('crash before marker')
            original(path, value)
        with patch.object(migration, 'atomic_json', side_effect=fail_marker), self.assertRaises(OSError):
            migration.cutover(self.root, self.collections, prepared['migration_id'])
        migration.cutover(self.root, self.collections, prepared['migration_id'])
        os.environ['MAVERICK_USAGE_STORE'] = 'sqlite'
        self.state.usage_store = build_usage_store(self.root, self.collections)
        self.ingest('two', 200)
        with patch.object(migration, '_retire_after_rollback', side_effect=OSError('crash after marker')), self.assertRaises(OSError):
            migration.rollback(self.root, self.collections)
        self.assertTrue((self.root / USAGE_ROOT / 'usage.sqlite').exists())
        os.environ['MAVERICK_USAGE_STORE'] = 'document'
        self.state.usage_store = build_usage_store(self.root, self.collections)
        self.ingest('three', 300)
        migration.rollback(self.root, self.collections)
        self.assertFalse((self.root / USAGE_ROOT / 'usage.sqlite').exists())
        self.assertEqual(len(self.state.usage_store.list_samples()), 3)

    def test_missing_database_or_wrong_schema_never_create_or_migrate_implicitly(self):
        os.environ['MAVERICK_USAGE_STORE'] = 'sqlite'
        with self.assertRaisesRegex(RuntimeError, 'adapter changed'):
            build_usage_store(self.root, self.collections)
        marker = self.root / USAGE_ROOT / 'store.json'
        marker.write_text(json.dumps({'schema': 1, 'adapter': 'sqlite'}))
        with self.assertRaises(sqlite3.OperationalError):
            build_usage_store(self.root, self.collections)
        path = marker.parent / 'usage.sqlite'
        self.assertFalse(path.exists())
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('PRAGMA user_version=999')
        with self.assertRaisesRegex(RuntimeError, 'Unsupported'):
            build_usage_store(self.root, self.collections)

    def test_general_control_plane_migration_excludes_sqlite_usage_owner(self):
        source_root, target_root = self.root / 'source', self.root / 'target'
        source = build_control_plane_collections(ControlStoreSettings(kind='json', json_root=source_root))
        target = build_control_plane_collections(ControlStoreSettings(kind='json', json_root=target_root))
        source.usage.samples.replace_all([{'sample_id': 'preserved-source'}])
        self.assertIn('usage_samples', {spec.name for spec in control_plane_collection_specs(source)})
        os.environ['MAVERICK_USAGE_STORE'] = 'sqlite'
        copied = _copy_collections(source, target)
        self.assertNotIn('usage_samples', {item['name'] for item in copied})
        self.assertEqual(target.usage.samples.find({}), [])
        _clear_source_storage({'repository_root': str(self.root), 'include_document_usage': False,
            'source_adapter': {'kind': 'json', 'json_root': str(source_root)},
            'target_adapter': {'kind': 'json', 'json_root': str(target_root)}})
        self.assertEqual(source.usage.samples.find({}), [{'sample_id': 'preserved-source'}])
        # A custom document root may contain another persistence owner's directory.
        broad_root = self.root / 'data' / 'control-plane'
        owned_backup = broad_root / 'usage' / 'keep.sqlite'
        owned_backup.write_text('owned backup')
        _clear_source_storage({'repository_root': str(self.root), 'include_document_usage': True,
            'source_adapter': {'kind': 'json', 'json_root': str(broad_root)},
            'target_adapter': {'kind': 'json', 'json_root': str(target_root)}})
        self.assertEqual(owned_backup.read_text(), 'owned backup')

    def test_exclusive_handoff_cannot_be_entered_inside_observation(self):
        with usage_fence(self.root / USAGE_ROOT), self.assertRaisesRegex(RuntimeError, 'upgrade'):
            migration.prepare(self.root, self.collections)
