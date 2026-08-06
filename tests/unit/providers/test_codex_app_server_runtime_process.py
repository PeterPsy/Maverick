from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

importlib.import_module("core.providers.codex_app_server_runtime")
from core.providers import codex_app_server_runtime_process as runtime_process
from core.providers import codex_app_server_runtime_thread as runtime_thread
from core.providers.models import RuntimeBackendLaunchSpec
from core.runtime import process_control


class CodexAppServerRuntimeProcessTestCase(unittest.TestCase):
    def test_runtime_process_is_reset_to_neutral_oom_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            proc_root = Path(temp_dir)
            score_path = proc_root / "4321" / "oom_score_adj"
            score_path.parent.mkdir()
            score_path.write_text("0\n", encoding="ascii")

            configured = process_control.configure_runtime_process_oom_score(
                SimpleNamespace(pid=4321),
                proc_root=proc_root,
            )
            score = score_path.read_text(encoding="ascii")

        self.assertTrue(configured)
        self.assertEqual(score, "0\n")

    def test_codex_runtime_launch_configures_oom_score_before_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session = SimpleNamespace(
                session_id="session-oom",
                workspace_id="default",
                runtime_root=str(Path(temp_dir) / "runtime"),
            )
            launch_spec = RuntimeBackendLaunchSpec(
                provider_id="codex",
                command=["codex", "app-server"],
                env_overrides={},
                credential_binding_id=None,
                resolved_secret_refs=[],
                working_directory=temp_dir,
                execution_mode="sandbox",
                readable_roots=[],
                writable_roots=[],
            )
            class FakeProcess:
                pid = 4321
                stdout: list[str] = []

                @staticmethod
                def poll():
                    return None

            process = FakeProcess()
            thread = SimpleNamespace(start=lambda: None)
            runtime_thread._RUNTIMES.pop(session.session_id, None)

            with patch.object(runtime_thread, "configure_runtime_process_oom_score") as configure_oom, patch.object(
                runtime_thread.threading,
                "Thread",
                return_value=thread,
            ), patch.object(runtime_thread, "_send_request", return_value={}):
                runtime = runtime_thread._ensure_runtime(
                    session=session,
                    launch_spec=launch_spec,
                    command_runner=lambda *_args, **_kwargs: process,
                )

            runtime_thread._RUNTIMES.pop(session.session_id, None)
            runtime_thread.unregister_runtime_process(session.session_id, process)

        self.assertIs(runtime.process, process)
        configure_oom.assert_called_once_with(process)

    def test_warm_turn_skips_repeated_generated_skill_cleanup_and_reports_startup_spans(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_home = Path(temp_dir) / "codex-home"
            session = SimpleNamespace(
                session_id="session-warm",
                workspace_id="default",
                runtime_root=str(Path(temp_dir) / "runtime"),
            )
            launch_spec = RuntimeBackendLaunchSpec(
                provider_id="codex",
                command=["codex", "app-server"],
                env_overrides={"CODEX_HOME": str(runtime_home)},
                credential_binding_id=None,
                resolved_secret_refs=[],
                working_directory=temp_dir,
                execution_mode="sandbox",
                readable_roots=[],
                writable_roots=[],
            )
            process = SimpleNamespace(pid=123, poll=lambda: None)
            runtime = runtime_process._CodexAppServerRuntime(
                session_id=session.session_id,
                workspace_id=session.workspace_id,
                runtime_root=session.runtime_root,
                process=process,
            )
            startup_events: list[tuple[str, dict[str, object]]] = []
            accepted_events: list[dict[str, object]] = []

            def send_request(_runtime, method, _params, *, timeout, on_sent=None):
                self.assertEqual(method, "turn/start")
                self.assertEqual(timeout, 20.0)
                if on_sent is not None:
                    on_sent({"request_id": 1})
                _runtime.completion_queue.put({"status": "completed"})
                return {"turn": {"id": "provider-turn-1"}}

            with patch.object(runtime_process, "_ensure_runtime", return_value=runtime), patch.object(
                runtime_process,
                "_ensure_provider_thread",
                return_value="provider-thread-1",
            ), patch.object(runtime_process, "_send_request", side_effect=send_request), patch.object(
                runtime_process,
                "_debug_log",
            ), patch(
                "core.providers.codex_app_server_runtime_thread.remove_codex_system_skills",
            ) as remove_system_skills:
                for _index in range(2):
                    runtime_process.execute_codex_app_server_turn(
                        session=session,
                        launch_spec=launch_spec,
                        input_text="hello",
                        event_sink=None,
                        timeout_seconds=1,
                        on_provider_startup_event=lambda phase, metadata: startup_events.append((phase, metadata)),
                        on_provider_accepted=accepted_events.append,
                    )

        remove_system_skills.assert_called_once_with(runtime_home)
        phases = [phase for phase, _metadata in startup_events]
        for expected_phase in (
            "remove_generated_skills_started",
            "remove_generated_skills_completed",
            "event_sink_reset_started",
            "event_sink_reset_completed",
        ):
            self.assertEqual(phases.count(expected_phase), 2)
        completed_cleanup_events = [
            metadata for phase, metadata in startup_events if phase == "remove_generated_skills_completed"
        ]
        self.assertEqual(completed_cleanup_events[0]["source"], "removed")
        self.assertEqual(completed_cleanup_events[1]["source"], "already_clean")
        self.assertEqual(len(accepted_events), 2)
        self.assertGreaterEqual(accepted_events[0]["turn_start_request_ack_ms"], 0)
        self.assertGreaterEqual(accepted_events[0]["event_sink_reset_ms"], 0)


if __name__ == "__main__":
    unittest.main()
