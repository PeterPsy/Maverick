#!/usr/bin/env python3
"""Repeatable isolated adapter/service probe; explicitly not an HTTP or device benchmark."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import timedelta
import json
import math
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'apps/storage/backend'))

from tests.support.performance_fixtures import EPOCH, storage_files, usage_document_state
from core.usage.service import ingest_runtime_usage
import inventory


def disk_bytes() -> int:
    try:
        values = dict(line.split(': ', 1) for line in Path('/proc/self/io').read_text().splitlines())
        return int(values['write_bytes'])
    except (OSError, KeyError):
        return 0


def measure(call, requests: int, warmup: int) -> dict:
    for _ in range(warmup):
        call()
    timings = []
    before = disk_bytes()
    for _ in range(requests):
        start = time.perf_counter()
        call()
        timings.append(1000 * (time.perf_counter() - start))
    return {'requests': requests, 'warmup': warmup,
            'median_ms': statistics.median(timings), 'p95_ms': sorted(timings)[math.ceil(.95 * requests) - 1],
            'maximum_ms': max(timings), 'process_physical_write_bytes': disk_bytes() - before}


def storage_probe(root: Path, count: int, shape: str, requests: int, warmup: int, *, adapter: str = 'json') -> dict:
    uploaded, generated, data = storage_files(root, count, shape=shape)
    inventory.sync_inventory(data, uploaded_root=uploaded, generated_root=generated)
    if adapter == 'sqlite':
        from inventory_migration import prepare_inventory, cutover_inventory
        prepared = prepare_inventory(data, uploaded_root=uploaded, generated_root=generated)
        cutover_inventory(data, prepared['migration_id'], uploaded_root=uploaded, generated_root=generated)

    def call():
        result = inventory.catalog_inventory_payload(data_root=data, uploaded_root=uploaded,
            generated_root=generated, role='generated', limit=100)
        assert result['pagination']['total'] == count
        assert len(result['files']) == min(count, 100)

    result = measure(call, requests, warmup)
    counts = Counter()
    original_stat, original_scan = Path.stat, os.scandir

    def stat(path, *args, **kwargs):
        counts['stat_calls'] += 1
        return original_stat(path, *args, **kwargs)

    def scan(*args, **kwargs):
        counts['scandir_calls'] += 1
        return original_scan(*args, **kwargs)

    with patch.object(Path, 'stat', stat), patch('os.scandir', scan):
        call()
    return {**result, 'one_instrumented_read': dict(counts), 'shape': shape, 'adapter': adapter}


def usage_probe(root: Path, count: int, requests: int, warmup: int) -> dict:
    state = usage_document_state(root, count)
    sequence = count

    def call():
        nonlocal sequence
        sequence += 1
        result = ingest_runtime_usage(state, session_id='root-0', turn_id=f'turn-{sequence}',
            observed_at=EPOCH + timedelta(seconds=sequence), payload={
                'usage_id': f'probe-{sequence}', 'provider_id': 'codex', 'model_id': 'model-0',
                'semantics': 'incremental', 'input_tokens': 120, 'cached_input_tokens': 20,
                'output_tokens': 55, 'reasoning_output_tokens': 5, 'total_tokens': 175,
            })
        assert result is not None and result.inserted
    return measure(call, requests, warmup)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain', choices=('storage', 'usage'), required=True)
    parser.add_argument('--count', type=int, default=10000)
    parser.add_argument('--requests', type=int, default=500)
    parser.add_argument('--warmup', type=int, default=5)
    parser.add_argument('--shape', choices=('flat', 'tree'), default='flat')
    parser.add_argument('--storage-adapter', choices=('json', 'sqlite'), default='json')
    args = parser.parse_args()
    if args.count < 1 or args.requests < 1 or args.warmup < 0:
        parser.error('count and requests must be positive; warmup cannot be negative')
    with tempfile.TemporaryDirectory(prefix='maverick-performance-') as scratch:
        root = Path(scratch)
        result = storage_probe(root, args.count, args.shape, args.requests, args.warmup, adapter=args.storage_adapter) if args.domain == 'storage' else usage_probe(root, args.count, args.requests, args.warmup)
    revision = subprocess.check_output(['git', '-c', f'safe.directory={ROOT}', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    print(json.dumps({'schema': 1, 'boundary': 'isolated-service', 'domain': args.domain,
        'dataset_count': args.count, 'fixture_revision': 1, 'source_commit': revision,
        'source_dirty': bool(subprocess.check_output(['git', '-c', f'safe.directory={ROOT}', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
        'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
        'cpu_count': os.cpu_count(), 'system': platform.system(), 'machine': platform.machine(),
        'result': result}, indent=2))


if __name__ == '__main__':
    main()
