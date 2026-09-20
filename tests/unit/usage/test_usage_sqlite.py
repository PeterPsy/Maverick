"""Both usage adapters must preserve the public metering contract."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.unit.usage import test_usage_service as contract
from core.usage.service import build_chat_usage_summary, ingest_runtime_usage
from core.usage.sqlite_store import UsageSqliteStore
from core.usage.timeseries import usage_timeseries_payload


@unittest.skipIf(sqlite3.sqlite_version_info < (3, 51, 3), 'Requires the verified WAL-safe runtime')
class UsageSqliteContractTests(contract.UsageServiceTest):
    def setUp(self):
        super().setUp()
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.store = UsageSqliteStore(Path(self.scratch.name) / 'usage.sqlite')
        self.store.initialize()
        self.state.usage_store = self.store

    def ingest(self, identity, minute, total, *, model='gpt-test', session=None, semantics='cumulative'):
        return ingest_runtime_usage(self.state, session_id=session or self.root.session_id, turn_id='turn',
            observed_at=datetime(2026, 8, 20, 10, tzinfo=UTC) + timedelta(minutes=minute), payload={
                'usage_id': identity, 'provider_id': 'codex', 'model_id': model, 'semantics': semantics,
                'input_tokens': total, 'total_tokens': total, 'context_tokens': 10,
            })

    def test_ingest_and_get_never_scan_history_or_repair_on_read(self):
        with patch.object(self.store, 'list_samples', side_effect=AssertionError('history scan')):
            result = self.ingest('one', 1, 100)
            self.assertEqual(result.summary.tokens.total_tokens, 100)
            with self.store.connection() as connection:
                connection.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action in
                    (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) else sqlite3.SQLITE_OK)
                from core.usage.sqlite_queries import chat_summary, timeseries
                self.assertEqual(chat_summary(connection, workspace_id=self.root.workspace_id,
                    root_session_id=self.root.session_id, direct_session_ids={self.root.session_id}).sample_count, 1)
                timeseries(connection, workspace_id=self.root.workspace_id, resolution='hour', periods=24)

    def test_late_cumulative_sample_compensates_only_its_successor(self):
        self.ingest('first', 1, 100)
        self.ingest('third', 3, 300)
        late = self.ingest('second', 2, 200)
        self.assertEqual(late.summary.tokens.total_tokens, 300)
        self.assertEqual([sample.total_tokens for sample in self.store.list_samples()], [100, 100, 100])
        self.assertFalse(self.ingest('second', 2, 200).inserted)
        self.assertEqual(self.ingest('reset', 4, 50).summary.tokens.total_tokens, 350)
        self.assertEqual(self.ingest('new-model', 5, 80, model='different').summary.tokens.total_tokens, 430)

    def test_failure_rolls_back_sample_stream_and_projections(self):
        self.ingest('one', 1, 100)
        with patch('core.usage.sqlite_store.adjust_projections', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.ingest('two', 2, 200)
        self.assertEqual(len(self.store.list_samples()), 1)
        self.assertEqual(self.ingest('two', 2, 200).summary.tokens.total_tokens, 200)

    def test_session_deletion_removes_all_its_projections(self):
        self.ingest('root', 1, 100)
        self.ingest('child', 2, 70, session=self.child.session_id)
        self.assertEqual(self.store.delete_sessions([self.child.session_id]), {self.child.session_id: 1})
        summary = build_chat_usage_summary(self.store, workspace_id=self.root.workspace_id, root_session_id=self.root.session_id)
        self.assertEqual(summary.tokens.total_tokens, 100)
        self.assertEqual(summary.delegated_tokens.total_tokens, 0)
        series = usage_timeseries_payload(self.store, workspace_id=self.root.workspace_id, resolution='hour', periods=1,
            now=datetime(2026, 8, 20, 10, 30, tzinfo=UTC))
        self.assertEqual(series['totals']['total_tokens'], 100)
        self.assertEqual(series['items'][0]['sample_count'], 1)

    def test_concurrent_processes_deduplicate_and_crash_cannot_half_commit(self):
        self.ingest('base', 1, 10, semantics='incremental')
        script = """
from dataclasses import replace
import os
from pathlib import Path
import sys
from core.usage.sqlite_store import UsageSqliteStore
store = UsageSqliteStore(Path(sys.argv[1]))
base = store.list_samples()[0]
if sys.argv[2] == 'crash':
    import core.usage.sqlite_store as module
    original = module.adjust_projections
    def fail(connection, sample, direction):
        original(connection, sample, direction)
        os._exit(19)
    module.adjust_projections = fail
for index in range(50):
    sample = replace(base, sample_id=('crash' if sys.argv[2] == 'crash' else 'shared') + str(index))
    store.ingest_observation(lambda history: sample, payload={})
"""
        def run(mode):
            return subprocess.run([sys.executable, '-c', script, str(self.store.path), mode],
                capture_output=True, text=True, timeout=30)
        with ThreadPoolExecutor(max_workers=2) as workers:
            for result in workers.map(run, ['normal', 'normal']):
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.store.list_samples()), 51)
        result = run('crash')
        self.assertEqual(result.returncode, 19, result.stderr)
        self.assertEqual(len(self.store.list_samples()), 51)
        summary = build_chat_usage_summary(self.store, workspace_id=self.root.workspace_id, root_session_id=self.root.session_id)
        self.assertEqual(summary.tokens.total_tokens, 510)
        self.assertEqual(summary.sample_count, 51)

    def test_late_earlier_sample_restores_successor_cost_and_latest_baseline(self):
        base = datetime(2026, 8, 20, 10, tzinfo=UTC)
        def ingest(identity, minute, total, cost):
            return ingest_runtime_usage(self.state, session_id=self.root.session_id, turn_id='turn',
                observed_at=base + timedelta(minutes=minute), payload={
                    'usage_id': identity, 'provider_id': 'codex', 'source': 'codex_app_server',
                    'semantics': 'cumulative', 'input_tokens': total, 'total_tokens': total,
                    'context_tokens': 10, 'context_window_tokens': 100, 'estimated_cost_microusd': cost})
        self.assertEqual(ingest('later', 2, 1000, 70).summary.tokens.total_tokens, 0)
        late = ingest('earlier', 1, 700, 50)
        self.assertEqual(late.summary.tokens.total_tokens, 300)
        self.assertEqual(late.summary.estimated_cost_microusd, 70)
        self.assertEqual([sample.total_tokens for sample in self.store.list_samples()], [0, 300])


if __name__ == '__main__':
    unittest.main()
