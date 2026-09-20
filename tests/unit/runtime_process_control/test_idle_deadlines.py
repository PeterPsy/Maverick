"""A single owner coalesces prewarm/reap deadlines and excludes newly active work."""

from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.runtime.runtime_idle_deadlines import RuntimeIdleDeadlines
from core.runtime.runtime_process_lifecycle import release_idle_runtime_processes


class IdleDeadlineTests(unittest.TestCase):
    def test_one_owner_replaces_session_deadlines_without_a_thread_per_session(self):
        deadlines = RuntimeIdleDeadlines()
        owner = object()
        called = []
        finished = Event()
        try:
            for index in range(100):
                deadlines.schedule(owner, str(index), 'reap', 180, lambda: called.append('stale'))
            thread = deadlines._thread
            for _ in range(100):
                deadlines.schedule(owner, 'same', 'prewarm', 180, lambda: called.append('stale'))
            self.assertIs(deadlines._thread, thread)
            self.assertEqual(len(deadlines._pending), 101)
            deadlines.schedule(owner, 'same', 'prewarm', .01, lambda: (called.append('fresh'), finished.set()))
            self.assertTrue(finished.wait(1))
            self.assertEqual(called, ['fresh'])
        finally:
            deadlines.cancel_owner(owner)
            if deadlines._thread:
                deadlines._thread.join(timeout=1)
        self.assertFalse(deadlines._pending)

    def test_active_turn_is_rechecked_inside_the_provider_lifecycle_fence(self):
        turns = []
        @contextmanager
        def handoff(**_kwargs):
            turns.append(SimpleNamespace(status='queued'))
            yield
        store = SimpleNamespace(get_session=lambda _: SimpleNamespace(workspace_id='workspace'),
            session_lifecycle_handoff=handoff, list_turns=lambda _: turns)
        with patch('core.runtime.runtime_process_lifecycle._release_idle_runtime_processes_now') as reap:
            self.assertEqual(release_idle_runtime_processes(SimpleNamespace(runtime_store=store),
                session_id='session', provider_id='provider', reason='deadline', idle_ttl_seconds=0), 0)
            reap.assert_not_called()

    def test_retention_budget_is_separate_by_owner_workspace_and_action(self):
        deadlines = RuntimeIdleDeadlines()
        state, other_state = object(), object()
        retired = Event()
        unexpected = Event()
        try:
            deadlines.schedule(state, 'old', 'reap', 180, retired.set, retention_group=('w1', 'alice'))
            deadlines.schedule(state, 'bob', 'reap', 180, unexpected.set, retention_group=('w1', 'bob'))
            deadlines.schedule(state, 'elsewhere', 'reap', 180, unexpected.set, retention_group=('w2', 'alice'))
            deadlines.schedule(state, 'old', 'prewarm', 180, unexpected.set)
            deadlines.schedule(other_state, 'other', 'reap', 180, unexpected.set, retention_group=('w1', 'alice'))
            deadlines.schedule(state, 'new', 'reap', 180, unexpected.set, retention_group=('w1', 'alice'))
            self.assertTrue(retired.wait(1))
            self.assertFalse(unexpected.is_set())
            self.assertEqual(len(deadlines._pending), 5)
        finally:
            deadlines.cancel_owner(state)
            deadlines.cancel_owner(other_state)
            if deadlines._thread:
                deadlines._thread.join(timeout=1)
        self.assertFalse(deadlines._pending)

    def test_refresh_of_same_session_preserves_its_full_ttl(self):
        deadlines = RuntimeIdleDeadlines()
        owner = object()
        called = Event()
        try:
            deadlines.schedule(owner, 'session', 'reap', 180, called.set, retention_group=('w', 'alice'))
            deadlines.schedule(owner, 'session', 'reap', 180, called.set, retention_group=('w', 'alice'))
            self.assertFalse(called.wait(.03))
            self.assertEqual(len(deadlines._pending), 1)
        finally:
            deadlines.cancel_owner(owner)
            if deadlines._thread:
                deadlines._thread.join(timeout=1)
