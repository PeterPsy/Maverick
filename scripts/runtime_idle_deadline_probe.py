#!/usr/bin/env python3
"""Real wall-clock validation of the shared deadline owner, without provider execution."""

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from threading import Event
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.runtime.runtime_idle_deadlines import RuntimeIdleDeadlines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ttl', type=float, default=180)
    parser.add_argument('--resources', type=int, default=64)
    args = parser.parse_args()
    if args.ttl <= 0 or args.resources < 1:
        parser.error('ttl and resources must be positive')
    deadlines = RuntimeIdleDeadlines()
    owner, done = object(), Event()
    lateness = []
    elapsed = []
    started, cpu_started = time.monotonic(), time.process_time()
    def fired(expected):
        now = time.monotonic()
        lateness.append(now - expected)
        elapsed.append(now - started)
        if len(lateness) == args.resources:
            done.set()
    try:
        threads = set()
        for number in range(args.resources):
            expected = time.monotonic() + args.ttl
            deadlines.schedule(owner, str(number), 'reap', args.ttl, lambda expected=expected: fired(expected))
            threads.add(deadlines._thread)
        assert done.wait(args.ttl + 15), 'A deadline exceeded the scheduler tolerance'
        assert len(threads) == 1 and min(elapsed) >= args.ttl and max(lateness) <= 15
        result = {'scheduled_resources': args.resources, 'fired_resources': len(lateness),
            'owner_threads': len(threads), 'ttl_seconds': args.ttl,
            'minimum_elapsed_seconds': min(elapsed), 'maximum_elapsed_seconds': max(elapsed),
            'maximum_lateness_seconds': max(lateness), 'process_cpu_seconds': time.process_time() - cpu_started}
    finally:
        thread = deadlines._thread
        deadlines.cancel_owner(owner)
        if thread:
            thread.join(timeout=1)
            assert not thread.is_alive(), 'Deadline owner did not stop'
    git = ['git', '-c', f'safe.directory={ROOT}']
    print(json.dumps({'schema': 1, 'boundary': 'shared-idle-deadline-owner-real-time',
        'source_commit': subprocess.check_output([*git, 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_dirty': bool(subprocess.check_output([*git, 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
        'python': platform.python_version(), 'cpu_count': os.cpu_count(), 'result': result}, indent=2))


if __name__ == '__main__':
    main()
