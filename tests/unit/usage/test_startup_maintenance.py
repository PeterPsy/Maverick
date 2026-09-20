"""Stopped-backend cutover retries safely without migrating on ordinary restarts."""

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.usage.administration import usage_migration
from core.usage.bootstrap import build_usage_store
from core.usage.handoff import USAGE_ROOT, active_adapter
from core.usage.service import ingest_runtime_usage
from core.usage.startup_maintenance import require_stopped_backend, run_startup_cutover
from tests.unit.usage.test_usage_service import _RuntimeStore, _session


class StoppedBackendTests(unittest.TestCase):
    def test_only_stopped_control_group_or_this_prestart_process_is_accepted(self):
        for main, control, active, sub, kill, allowed in (
            ('1', '0', 'active', 'running', 'control-group', False),
            ('0', '2', 'activating', 'start-pre', 'control-group', False),
            ('0', '0', 'inactive', 'dead', 'process', False),
            ('0', '0', 'inactive', 'dead', 'control-group', True),
            ('0', str(os.getpid()), 'activating', 'start-pre', 'control-group', True),
        ):
            with self.subTest(state=(main, control, active, sub, kill)):
                result = SimpleNamespace(stdout=f'MainPID={main}\nControlPID={control}\nActiveState={active}\nSubState={sub}\nKillMode={kill}\n')
                with patch('core.usage.startup_maintenance.subprocess.run', return_value=result):
                    if allowed:
                        self.assertEqual(require_stopped_backend('maverick-core.service')['MainPID'], '0')
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'drained control group'):
                            require_stopped_backend('maverick-core.service')


@unittest.skipIf(sqlite3.sqlite_version_info < (3, 51, 3), 'Requires the verified WAL-safe runtime')
class StartupMaintenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.receipt = self.root / USAGE_ROOT / 'maintenance/cutover.json'
        environment = patch.dict(os.environ, {'MAVERICK_USAGE_STORE': 'document', 'MAVERICK_CONTROL_STORE': 'json',
            'MAVERICK_JSON_CONTROL_STORE_ROOT': str(self.root / 'json')})
        environment.start()
        self.addCleanup(environment.stop)
        self.collections = build_control_plane_collections(ControlStoreSettings.from_environment(repository_root=self.root)).usage
        self.document = build_usage_store(self.root, self.collections)
        self.state = SimpleNamespace(usage_store=self.document, runtime_store=_RuntimeStore(_session('root')), provider_registry=None)
        self.ingest('one', 100)
        os.environ['MAVERICK_USAGE_STORE'] = 'sqlite'
        stopped = patch('core.usage.startup_maintenance.require_stopped_backend', return_value={'MainPID': '0', 'KillMode': 'control-group'})
        stopped.start()
        self.addCleanup(stopped.stop)

    def ingest(self, identity, total):
        return ingest_runtime_usage(self.state, session_id='root', turn_id='turn', observed_at=datetime(2026, 9, 20, tzinfo=UTC),
            payload={'usage_id': identity, 'semantics': 'incremental', 'input_tokens': total, 'total_tokens': total})

    def test_promotes_and_backs_up_once_and_does_not_remigrate_after_rollback(self):
        before = self.document.list_samples()
        result = run_startup_cutover(self.root, self.receipt)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['backup']['counts']['samples'], 1)
        self.state.usage_store = build_usage_store(self.root, self.collections)
        self.assertEqual(self.state.usage_store.list_samples(), before)
        self.ingest('two', 200)
        usage_migration(self.root, {'phase': 'rollback'})
        os.environ['MAVERICK_USAGE_STORE'] = 'document'
        with patch('core.usage.startup_maintenance.usage_migration') as migrate:
            self.assertEqual(run_startup_cutover(self.root, self.receipt), result)
            migrate.assert_not_called()
        self.assertEqual(active_adapter(self.root / USAGE_ROOT), 'document')
        self.assertEqual(len(self.document.list_samples()), 2)

    def test_resumes_when_promotion_commits_before_its_receipt(self):
        def lose_reply(root, arguments):
            value = usage_migration(root, arguments)
            if arguments['phase'] == 'cutover':
                raise RuntimeError('lost reply')
            return value
        with patch('core.usage.startup_maintenance.usage_migration', side_effect=lose_reply):
            with self.assertRaisesRegex(RuntimeError, 'lost reply'):
                run_startup_cutover(self.root, self.receipt)
        self.assertEqual(active_adapter(self.root / USAGE_ROOT), 'sqlite')
        self.assertEqual(json.loads(self.receipt.read_text())['status'], 'prepared')
        result = run_startup_cutover(self.root, self.receipt)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['cutover']['status'], 'already_active')
        self.assertEqual(result['backup']['counts']['samples'], 1)

    def test_refuses_changed_source_after_failed_validation(self):
        def fail_validation(root, arguments):
            if arguments['phase'] == 'validate':
                raise RuntimeError('validation interrupted')
            return usage_migration(root, arguments)
        with patch('core.usage.startup_maintenance.usage_migration', side_effect=fail_validation):
            with self.assertRaisesRegex(RuntimeError, 'validation interrupted'):
                run_startup_cutover(self.root, self.receipt)
        self.ingest('unexpected', 200)
        with self.assertRaisesRegex(RuntimeError, 'source changed'):
            run_startup_cutover(self.root, self.receipt)
        self.assertEqual(active_adapter(self.root / USAGE_ROOT), 'document')

    def test_refuses_unrelated_active_migration_and_missing_target_configuration(self):
        os.environ['MAVERICK_USAGE_STORE'] = 'document'
        with self.assertRaisesRegex(RuntimeError, 'Configure MAVERICK_USAGE_STORE'):
            run_startup_cutover(self.root, self.receipt)
        self.assertFalse(self.receipt.exists())
        os.environ['MAVERICK_USAGE_STORE'] = 'sqlite'
        run_startup_cutover(self.root, self.receipt)
        with self.assertRaisesRegex(RuntimeError, 'Another Usage migration'):
            run_startup_cutover(self.root, self.receipt.with_name('unrelated.json'))
