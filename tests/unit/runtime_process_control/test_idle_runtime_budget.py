"""Idle provider retention closes actual owned processes without disturbing work."""

from contextlib import contextmanager
from threading import Event, RLock
from types import SimpleNamespace
import os
import subprocess
import unittest
from unittest.mock import patch
from uuid import uuid4

from core.runtime.runtime_idle_deadlines import RuntimeIdleDeadlines
from core.runtime.runtime_process_lifecycle import release_idle_runtime_processes


class IdleRuntimeBudgetTests(unittest.TestCase):
    def setUp(self):
        self.deadlines = RuntimeIdleDeadlines()
        self.sessions = {}
        self.turns = {}
        self.locks = {}
        self.state = SimpleNamespace(runtime_store=SimpleNamespace(
            get_session=self.sessions.__getitem__, list_turns=lambda key: self.turns[key],
            session_lifecycle_handoff=self.handoff,
        ), provider_store=SimpleNamespace(), runtime_event_bus=None)
        self.patch = patch('core.runtime.runtime_process_lifecycle.runtime_idle_deadlines', self.deadlines)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.shutdown)

    def shutdown(self):
        thread = self.deadlines._thread
        self.deadlines.cancel_owner(self.state)
        if thread:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    @contextmanager
    def handoff(self, *, workspace_id, session_id):
        with self.locks[session_id]:
            yield

    def session(self, owner='alice'):
        key = f'idle-budget-{uuid4().hex}'
        self.sessions[key] = SimpleNamespace(session_id=key, workspace_id='default', owner_user_id=owner)
        self.turns[key] = []
        self.locks[key] = RLock()
        return key

    def retain(self, key, ttl=180):
        return release_idle_runtime_processes(self.state, session_id=key, provider_id='codex',
            reason='test_idle_budget', idle_ttl_seconds=ttl)

    def process(self, session):
        process = subprocess.Popen(['bash', '-c', "exec -a 'codex app-server --listen stdio://' sleep 30"],
            env={**os.environ, 'MAVERICK_RUNTIME_SESSION_ID': session, 'MAVERICK_RUNTIME_ENGINE_ID': 'codex'})
        def close():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
        self.addCleanup(close)
        return process

    def test_new_idle_session_retires_only_previous_owner_process(self):
        old, newest, other = self.session(), self.session(), self.session('bob')
        old_process, new_process, other_process = self.process(old), self.process(newest), self.process(other)
        with patch('core.runtime.runtime_process_lifecycle.record_runtime_event') as record:
            self.retain(old)
            self.retain(other)
            self.retain(newest)
            old_process.wait(timeout=3)
            self.assertIsNone(new_process.poll())
            self.assertIsNone(other_process.poll())
            # Drain the callback before checking its event or closing the fixture.
            self.shutdown()
            record.assert_called_once()
            self.assertEqual(record.call_args.kwargs['session_id'], old)

    def test_new_work_admitted_before_displacement_is_never_closed(self):
        for status in ('queued', 'active', 'waiting_for_tool_confirmation'):
            with self.subTest(status=status):
                old, newest = self.session(), self.session()
                retired = Event()
                def close(_state, *, session_id, **_kwargs):
                    self.assertNotEqual(session_id, old)
                    retired.set()
                    return 1
                with patch('core.runtime.runtime_process_lifecycle._release_idle_runtime_processes_now', close):
                    self.retain(old)
                    self.turns[old] = [SimpleNamespace(status=status)]
                    self.retain(newest, ttl=.02)
                    self.assertTrue(retired.wait(1))
                    self.shutdown()

    def test_new_deadline_supersedes_callback_waiting_for_lifecycle_fence(self):
        session = self.session()
        entered = Event()
        initial_handoff = self.state.runtime_store.session_lifecycle_handoff
        @contextmanager
        def observed_handoff(**kwargs):
            entered.set()
            with initial_handoff(**kwargs):
                yield
        with patch('core.runtime.runtime_process_lifecycle._release_idle_runtime_processes_now') as close:
            with self.locks[session]:
                self.retain(session, ttl=.01)
                self.state.runtime_store.session_lifecycle_handoff = observed_handoff
                self.assertTrue(entered.wait(1))
                self.retain(session)
            # Wait for the superseded callback to leave the same dispatcher.
            finished = Event()
            self.deadlines.schedule(self.state, 'barrier', 'test', 0, finished.set)
            self.assertTrue(finished.wait(1))
            close.assert_not_called()
            self.assertTrue(self.deadlines.pending(self.state, session, 'reap'))
