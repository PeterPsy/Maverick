#!/usr/bin/env python3
"""Measure the real idle TTL/budget with disposable session-owned child processes.

The children imitate local provider process identity; no external model/provider
request is made. Production lifecycle guards and orphan-process retirement run
unchanged against a disposable RuntimeDocumentStore.
"""

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.runtime.runtime_idle_deadlines import runtime_idle_deadlines
from core.runtime.runtime_process_lifecycle import release_idle_runtime_processes
from core.runtime.service import create_runtime_session, queue_runtime_turn, transition_runtime_turn
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ttl', type=float, default=180)
    args = parser.parse_args()
    if args.ttl <= 0:
        parser.error('ttl must be positive')
    store = RuntimeDocumentStore(RuntimeCollections(**{key: FakeCollection() for key in (
        'sessions', 'turns', 'events', 'processes', 'states', 'threads')}))
    state = SimpleNamespace(runtime_store=store, provider_store=SimpleNamespace(), runtime_event_bus=None)
    processes = {}
    sessions = {}
    scheduled = {}
    cpu_started = time.process_time()
    def retain(name):
        scheduled[name] = time.monotonic()
        release_idle_runtime_processes(state, session_id=sessions[name], provider_id='codex',
            reason='idle_process_probe', idle_ttl_seconds=args.ttl)
    try:
        for name, owner in (('active', 'alice'), ('old', 'alice'), ('latest', 'alice'), ('other', 'bob')):
            key = f'idle-probe-{uuid4().hex}'
            session = create_runtime_session(store, session_id=key, workspace_id='fixture', agent_id='fixture')
            store.save_session(replace(session, owner_user_id=owner))
            sessions[name] = key
            processes[name] = subprocess.Popen(['bash', '-c',
                f"exec -a 'codex app-server --listen stdio://' sleep {args.ttl + 30}"],
                env={**os.environ, 'MAVERICK_RUNTIME_SESSION_ID': key, 'MAVERICK_RUNTIME_ENGINE_ID': 'codex'})
        retain('active')
        turn = queue_runtime_turn(store, turn_id=f'turn-{uuid4().hex}', session_id=sessions['active'], input_text='fixture')
        transition_runtime_turn(store, turn_id=turn.turn_id, target_status='active')
        retain('old')
        retain('other')
        retain('latest')
        processes['old'].wait(timeout=15)
        displaced_after = time.monotonic() - scheduled['latest']
        assert processes['active'].poll() is None, 'Budget interrupted active work'
        assert processes['other'].poll() is None, 'Budget crossed user owners'
        assert processes['latest'].poll() is None, 'Latest idle runtime was not retained'
        exits = {}
        deadline = max(scheduled.values()) + args.ttl + 15
        while len(exits) < 2 and time.monotonic() < deadline:
            for name in ('latest', 'other'):
                if name not in exits and processes[name].poll() is not None:
                    exits[name] = time.monotonic() - scheduled[name]
            assert processes['active'].poll() is None, 'TTL interrupted active work'
            if len(exits) < 2:
                time.sleep(.05)
        assert len(exits) == 2, 'Idle provider did not retire within TTL + 15 seconds'
        assert all(args.ttl <= elapsed <= args.ttl + 15 for elapsed in exits.values()), exits
        # Process exit precedes the final retirement event; drain the dispatcher
        # before inspecting the persisted observations.
        thread = runtime_idle_deadlines._thread
        if thread:
            thread.join(timeout=2)
            assert not thread.is_alive(), 'Retirement callbacks did not complete'
        result = {'ttl_seconds': args.ttl, 'idle_exit_seconds': exits,
            'budget_displacement_seconds': displaced_after, 'retained_idle_per_owner': 1,
            'active_process_preserved': True, 'process_cpu_seconds': time.process_time() - cpu_started,
            'retirement_events': {name: len([event for event in store.list_events(key)
                if event.event_type == 'runtime.process.idle_reaped']) for name, key in sessions.items()}}
        assert result['retirement_events'] == {'active': 0, 'old': 1, 'latest': 1, 'other': 1}, result
    finally:
        thread = runtime_idle_deadlines._thread
        runtime_idle_deadlines.cancel_owner(state)
        if thread:
            thread.join(timeout=2)
            assert not thread.is_alive(), 'Deadline dispatcher did not stop'
        for process in processes.values():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
    git = ['git', '-c', f'safe.directory={ROOT}']
    print(json.dumps({'schema': 1, 'boundary': 'real-owned-processes-simulated-provider-identity',
        'source_commit': subprocess.check_output([*git, 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_dirty': bool(subprocess.check_output([*git, 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
        'python': platform.python_version(), 'result': result}, indent=2))


if __name__ == '__main__':
    main()
