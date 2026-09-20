#!/usr/bin/env python3
"""Authenticated loopback HTTP probe of real mounted Storage in a disposable tenant."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.client import HTTPConnection
import json
import math
import os
from pathlib import Path
import platform
import shutil
from socketserver import ThreadingMixIn
import sqlite3
import statistics
import sys
import tempfile
from threading import Thread
import time
from unittest.mock import patch
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'apps/storage/backend')]

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.service import install_store_app, register_app_source_from_contract
from tests.support.performance_fixtures import storage_files
from inventory_migration import prepare_inventory, cutover_inventory
import inventory_legacy


class Server(ThreadingMixIn, WSGIServer):
    daemon_threads = False


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *_):
        pass


@contextmanager
def mounted_storage(root: Path, count: int, shape: str, *, profile: bool = False):
    for name in ('core', 'apps', 'workspaces', 'scripts', 'docs'):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / 'AGENTS.md').write_text('Disposable mounted performance fixture.\n')
    source_root = root / 'apps/storage'
    shutil.copytree(ROOT / 'apps/storage', source_root,
        ignore=shutil.ignore_patterns('node_modules', 'frontend', '__pycache__', 'tests'))
    # Contract validation includes widget mounts. Assets are copied, never rebuilt or served by the probe.
    shutil.copytree(ROOT / 'apps/storage/frontend/dist', source_root / 'frontend/dist')
    uploaded, generated, data = storage_files(root / 'workspaces/default', count, shape=shape)
    inventory_legacy.sync_inventory(data, uploaded_root=uploaded, generated_root=generated)
    migration = prepare_inventory(data, uploaded_root=uploaded, generated_root=generated)
    cutover_inventory(data, migration['migration_id'], uploaded_root=uploaded, generated_root=generated)
    with patch.dict(os.environ, {'MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS': '1',
            'MAVERICK_ADMIN_USERNAME': 'fixture-admin', 'MAVERICK_ADMIN_PASSWORD': 'fixture-only-password',
            'MAVERICK_USAGE_STORE': 'document', 'PYTHONPATH': str(ROOT)}):
        state = bootstrap_platform_state(start_path=root)
        source = register_app_source_from_contract(state.app_store, source_kind='platform', source_path=str(source_root))
        install_store_app(state.app_store, source_id=source.source_id, workspace_id='default', start_path=root)
        host = PlatformHost(state, start_path=root)
        import cProfile
        import pstats
        profiler = cProfile.Profile() if profile else None
        def profiled_host(environ, start_response):
            return profiler.runcall(host, environ, start_response) if profiler else host(environ, start_response)
        with make_server('127.0.0.1', 0, profiled_host, server_class=Server, handler_class=QuietHandler) as server:
            thread = Thread(target=server.serve_forever, name='mounted-performance-http')
            thread.start()
            try:
                client = Client(server.server_port)
                client.login()
                yield client
            finally:
                server.shutdown()
                thread.join(timeout=10)
                if profiler:
                    pstats.Stats(profiler, stream=sys.stderr).sort_stats("cumulative").print_stats(30)


class Client:
    def __init__(self, port: int):
        self.port, self.cookie = port, ''

    def request(self, path: str, body: dict | None = None):
        connection = HTTPConnection('127.0.0.1', self.port, timeout=60)
        try:
            headers = {'Origin': f'http://127.0.0.1:{self.port}', 'Content-Type': 'application/json'}
            if self.cookie:
                headers['Cookie'] = self.cookie
            if body is not None and path == '/api/apps/storage/backend':
                body = {**body, '_app_secret_request': {'logical_names': [], 'required': False}}
            connection.request('POST' if body is not None else 'GET', path,
                body=json.dumps(body) if body is not None else None, headers=headers)
            response = connection.getresponse()
            payload = json.loads(response.read())
            if response.status != 200:
                raise RuntimeError(f'{path}: {response.status}: {payload}')
            if path == '/api/auth/login':
                self.cookie = response.getheader('Set-Cookie').split(';', 1)[0]
            return payload
        finally:
            connection.close()

    def login(self):
        self.request('/api/auth/login', {'username': 'fixture-admin', 'password': 'fixture-only-password'})


def stats(timings: list[float]) -> dict:
    return {'requests': len(timings), 'median_ms': statistics.median(timings),
        'p95_ms': sorted(timings)[math.ceil(.95 * len(timings)) - 1], 'maximum_ms': max(timings)}


def run(client: Client, requests: int, warmup: int, *, concurrent: bool) -> dict:
    route = '/api/apps/storage/backend'
    body = {'action': 'catalog', 'role': 'generated', 'limit': 100, 'sort_by': 'created_at'}
    page = client.request(route, body)
    file_id = page['files'][0]['id']
    actions = {
        'catalog': lambda _: client.request(route, body),
        'resolver': lambda _: client.request('/api/app-references/resolve', {'app_id': 'storage', 'entity_type': 'file', 'entity_id': file_id}),
    }
    results = {}
    for name, read in actions.items():
        for number in range(warmup):
            read(number)

        def worker(worker_id: int, count: int, write: bool = False):
            timings = []
            for number in range(count):
                started = time.perf_counter()
                if write:
                    client.request(route, {'action': 'write_file', 'role': 'generated',
                        'relative_path': f'probe-{name}-{worker_id}-{number}.md', 'content': '# Concurrent fixture\n'})
                else:
                    result = read(number)
                    if name == 'catalog':
                        assert len(result['files']) == 100 and result['pagination']['total'] >= 100
                timings.append((time.perf_counter() - started) * 1000)
            return timings

        if concurrent:
            with ThreadPoolExecutor(max_workers=6) as pool:
                readers = [pool.submit(worker, index, requests // 4 + int(index < requests % 4)) for index in range(4)]
                writers = [pool.submit(worker, index, max(1, requests // 4), True) for index in (4, 5)]
                read_times = [sample for task in readers for sample in task.result()]
                write_times = [sample for task in writers for sample in task.result()]
            results[name] = {'reads': stats(read_times), 'writes': stats(write_times)}
        else:
            results[name] = {'reads': stats(worker(0, requests))}
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=10000)
    parser.add_argument('--shape', choices=('flat', 'tree'), default='flat')
    parser.add_argument('--requests', type=int, default=500)
    parser.add_argument('--warmup', type=int, default=5)
    parser.add_argument('--concurrent', action='store_true')
    parser.add_argument('--profile', action='store_true')
    args = parser.parse_args()
    if args.profile and args.concurrent:
        parser.error('--profile requires sequential requests')
    with tempfile.TemporaryDirectory(prefix='maverick-mounted-probe-') as scratch:
        with mounted_storage(Path(scratch), args.count, args.shape, profile=args.profile) as client:
            results = run(client, args.requests, args.warmup, concurrent=args.concurrent)
    print(json.dumps({'boundary': 'authenticated-mounted-loopback-http', 'python': platform.python_version(),
        'sqlite': sqlite3.sqlite_version, 'fixture_count': args.count, 'shape': args.shape,
        'warmup': args.warmup, 'readers': 4 if args.concurrent else 1,
        'writers': 2 if args.concurrent else 0, 'results': results}, indent=2))


if __name__ == '__main__':
    main()
