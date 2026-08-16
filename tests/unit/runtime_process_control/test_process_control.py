from __future__ import annotations

from datetime import UTC, datetime
import os
import subprocess
import time
from types import SimpleNamespace
import unittest

from core.runtime.service import create_runtime_session, queue_runtime_turn, transition_runtime_turn
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.turn_submission import release_idle_runtime_processes
from tests.support.collections import FakeCollection


class RuntimeProcessControlTestCase(unittest.TestCase):
    def make_store(self) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )

    def test_idle_reaper_falls_back_to_codex_app_server_process_env(self) -> None:
        store = self.make_store()
        now = datetime(2026, 6, 16, tzinfo=UTC)
        create_runtime_session(
            store,
            session_id="sess-lost-codex-process",
            workspace_id="default",
            agent_id="agent-1",
            now=now,
        )
        turn = queue_runtime_turn(
            store,
            turn_id="turn-lost-codex-process",
            session_id="sess-lost-codex-process",
            input_text="done",
            now=now,
        )
        transition_runtime_turn(store, turn_id=turn.turn_id, target_status="active", now=now)
        transition_runtime_turn(store, turn_id=turn.turn_id, target_status="cancelled", now=now)

        env = {
            **os.environ,
            "MAVERICK_RUNTIME_SESSION_ID": "sess-lost-codex-process",
            "MAVERICK_RUNTIME_ENGINE_ID": "codex",
        }
        process = subprocess.Popen(
            ["bash", "-c", "exec -a 'codex app-server --listen stdio://' sleep 30"],
            env=env,
            start_new_session=True,
        )
        try:
            terminated = release_idle_runtime_processes(
                SimpleNamespace(
                    runtime_store=store,
                    runtime_event_bus=None,
                    provider_store=SimpleNamespace(),
                ),
                session_id="sess-lost-codex-process",
                provider_id="codex",
                reason="test_lost_codex_process",
                idle_ttl_seconds=0,
            )

            self.assertEqual(terminated, 1)
            deadline = time.monotonic() + 2
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertIsNotNone(process.poll())
            self.assertIn(
                "runtime.process.idle_reaped",
                [event.event_type for event in store.list_events("sess-lost-codex-process")],
            )
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
