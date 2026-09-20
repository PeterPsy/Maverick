#!/usr/bin/env python3
"""Real authenticated Usage chart HTTP reads with optional concurrent runtime ingestion."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
from threading import Thread
import time
from types import SimpleNamespace
from unittest.mock import patch
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.shared.entrypoints import EntrypointShutdownController
from core.usage.bootstrap import build_usage_store
from core.usage.migration import prepare, cutover
from core.usage.service import ingest_runtime_usage
from server_mounted_performance_probe import Client, QuietHandler, Server, stats
from server_performance_probe import disk_bytes
from tests.support.performance_fixtures import usage_sample


def run(client: Client, producer, *, count: int, requests: int, warmup: int, concurrent: bool) -> dict:
    route = '/api/usage/timeseries?resolution=day&periods=30'
    def read():
        result = client.request(route)
        assert len(result['items']) == 30 and result['totals']['total_tokens'] >= count * 175
        return result

    def observe(identity: str):
        result = ingest_runtime_usage(producer, session_id='root-0', turn_id=identity, payload={
            'usage_id': identity, 'provider_id': 'codex', 'model_id': 'model-0',
            'semantics': 'incremental', 'input_tokens': 120, 'cached_input_tokens': 20,
            'output_tokens': 55, 'reasoning_output_tokens': 5, 'total_tokens': 175,
        })
        assert result is not None and result.inserted

    for number in range(warmup):
        read()
        observe(f'warmup-{number}')
    expected_count = count + warmup

    def worker(worker_id: int, size: int, *, write: bool = False):
        timings = []
        for number in range(size):
            started = time.perf_counter()
            observe(f'probe-{worker_id}-{number}') if write else read()
            timings.append((time.perf_counter() - started) * 1000)
        return timings

    before = disk_bytes()
    if concurrent:
        with ThreadPoolExecutor(max_workers=6) as pool:
            readers = [pool.submit(worker, index, requests // 4 + int(index < requests % 4)) for index in range(4)]
            writers = [pool.submit(worker, index, max(1, requests // 4), write=True) for index in (4, 5)]
            reads = [value for task in readers for value in task.result()]
            writes = [value for task in writers for value in task.result()]
        expected_count += 2 * max(1, requests // 4)
    else:
        reads = worker(0, requests)
        writes = worker(1, requests, write=True)
        expected_count += requests
    written = disk_bytes() - before
    result = read()
    assert result['totals']['total_tokens'] == expected_count * 175, (result['totals'], expected_count)
    with producer.usage_store.transaction() as connection:
        observed_count = connection.execute('SELECT COUNT(*) FROM samples').fetchone()[0]
        assert observed_count == expected_count, (observed_count, expected_count)
    return {'http_chart_reads': stats(reads), 'runtime_observations': stats(writes),
        'process_physical_write_bytes': written, 'verified_sample_count': expected_count,
        'verified_total_tokens': result['totals']['total_tokens']}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=10000)
    parser.add_argument('--requests', type=int, default=500)
    parser.add_argument('--warmup', type=int, default=5)
    parser.add_argument('--concurrent', action='store_true')
    args = parser.parse_args()
    if args.count < 1 or args.requests < 1 or args.warmup < 0:
        parser.error('count and requests must be positive; warmup nonnegative')
    with tempfile.TemporaryDirectory(prefix='maverick-usage-http-') as scratch, patch.dict(os.environ, {
            'MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS': '1', 'MAVERICK_ADMIN_USERNAME': 'fixture-admin',
            'MAVERICK_ADMIN_PASSWORD': 'fixture-only-password', 'MAVERICK_USAGE_STORE': 'document'}):
        root = Path(scratch)
        for name in ('core', 'apps', 'workspaces', 'scripts', 'docs'):
            (root / name).mkdir()
        (root / 'AGENTS.md').write_text('Disposable Usage performance fixture.\n')
        state = bootstrap_platform_state(start_path=root)
        collections = state.usage_store.collections
        # Keep every fixture inside the real endpoint's rolling 30-day window.
        now = datetime.now(UTC)
        collections.samples.replace_all([asdict(replace(usage_sample(number), workspace_id='default',
            observed_at=now - timedelta(seconds=args.count - number))) for number in range(args.count)])
        migration = prepare(root, collections)
        cutover(root, collections, migration['migration_id'])
        os.environ['MAVERICK_USAGE_STORE'] = 'sqlite'
        state = replace(state, usage_store=build_usage_store(root, collections))
        session = SimpleNamespace(session_id='root-0', workspace_id='default', creator_runtime_session_id=None,
            execution_binding=None, hosted_provider_id=None, hosted_model_id=None, provider_id='codex')
        producer = SimpleNamespace(usage_store=state.usage_store, provider_registry=None,
            runtime_store=SimpleNamespace(get_session=lambda _: session))
        shutdown = EntrypointShutdownController()
        host = PlatformHost(state, start_path=root, shutdown_controller=shutdown)
        with make_server('127.0.0.1', 0, host, server_class=Server, handler_class=QuietHandler) as server:
            thread = Thread(target=server.serve_forever, name='usage-performance-http')
            thread.start()
            try:
                client = Client(server.server_port)
                client.login()
                result = run(client, producer, count=args.count, requests=args.requests,
                    warmup=args.warmup, concurrent=args.concurrent)
            finally:
                shutdown.begin_shutdown()
                server.shutdown()
                thread.join(timeout=10)
    git = ['git', '-c', f'safe.directory={ROOT}']
    print(json.dumps({'schema': 1, 'boundary': 'authenticated-loopback-http-and-internal-runtime-ingestion',
        'source_commit': subprocess.check_output([*git, 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_dirty': bool(subprocess.check_output([*git, 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
        'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version, 'cpu_count': os.cpu_count(),
        'system': platform.system(), 'machine': platform.machine(), 'fixture_count': args.count,
        'warmup': args.warmup, 'readers': 4 if args.concurrent else 1,
        'concurrent_writers': 2 if args.concurrent else 0, 'result': result}, indent=2))


if __name__ == '__main__':
    main()
