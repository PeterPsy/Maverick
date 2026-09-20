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
