#!/usr/bin/env python3
"""Isolated real-time Storage reconciliation probe with bounded scheduler delays."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'apps/storage/backend'))

from tests.support.performance_fixtures import storage_files
import inventory_legacy
from inventory_migration import prepare_inventory, cutover_inventory
from inventory_reconcile import reconcile_inventory
from inventory_sqlite import InventoryIndex


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=10000)
    parser.add_argument('--shape', choices=('flat', 'tree'), default='flat')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='storage-reconciliation-probe-') as scratch:
        uploaded, generated, data = storage_files(Path(scratch), args.count, shape=args.shape)
        roots = {'uploaded_root': uploaded, 'generated_root': generated}
        inventory_legacy.sync_inventory(data, **roots)
        migration = prepare_inventory(data, **roots)
        cutover_inventory(data, migration['migration_id'], **roots)
        index = InventoryIndex(data)
        with index.transaction() as connection:
            targets = [dict(row) for row in connection.execute("SELECT file_id,path FROM files WHERE provider='local' ORDER BY path LIMIT 1")]
            targets += [dict(row) for row in connection.execute("SELECT file_id,path FROM files WHERE provider='local' ORDER BY path DESC LIMIT 1")]
            for target in targets:
                target['signature'] = index.signature(connection, target['file_id'])
        for target in targets:
            path = generated / target['path']
            before = path.stat()
            path.write_bytes(path.read_bytes().replace(b'Fixture', b'Changed'))
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        started = time.monotonic()
        found = {}
        passes = []
        complete = False
        while (not complete or len(found) < len({target['file_id'] for target in targets})) and time.monotonic() - started < 90:
            result = reconcile_inventory(data, **roots)
            passes.append({key: result[key] for key in ('inspected', 'duration_ms', 'completed_directories', 'next_due_in_seconds')})
            with index.transaction() as connection:
                complete = connection.execute('SELECT 1 FROM scan_queue WHERE last_completed=0 LIMIT 1').fetchone() is None
                for target in targets:
                    if index.signature(connection, target['file_id']) != target['signature']:
                        found.setdefault(target['file_id'], time.monotonic() - started)
            if not complete or len(found) < len(targets):
                time.sleep(result['next_due_in_seconds'])
        print(json.dumps({'schema': 1, 'boundary': 'isolated-reconciliation-real-scheduler-delays',
            'sqlite': sqlite3.sqlite_version, 'count': args.count, 'shape': args.shape,
            'found_seconds': list(found.values()), 'all_found': len(found) == len(targets),
            'initial_cycle_completed': complete, 'total_seconds': time.monotonic() - started, 'passes': passes}, indent=2))


if __name__ == '__main__':
    main()
