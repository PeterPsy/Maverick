import os
import json
from pathlib import Path
import queue
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from core.providers.models import RuntimeBackendLaunchSpec
from core.providers.provider_codex import build_codex_definition
from core.providers.codex_app_server import _turn_sandbox_policy
from core.runtime.execution import execute_runtime_turn
from core.runtime.execution import _codex_app_server_command
from core.runtime.runtime_session import RuntimeSessionRecord


class RuntimeExecutionCommandTest(unittest.TestCase):
    def test_sandbox_session_uses_codex_app_server_without_legacy_landlock_flag(self) -> None:
        with patch.dict(os.environ, {"MAVERICK3_CODEX_COMMAND": "/usr/bin/codex"}, clear=False):
            command = _codex_app_server_command(execution_mode=_session("sandbox").effective_mode)

        self.assertEqual(command, ["/usr/bin/codex", "app-server", "--listen", "stdio://"])
        self.assertNotIn("exec", command)

    def test_full_access_session_uses_codex_app_server_without_landlock_flag(self) -> None:
        with patch.dict(os.environ, {"MAVERICK3_CODEX_COMMAND": "/usr/bin/codex"}, clear=False):
            command = _codex_app_server_command(execution_mode=_session("full-access").effective_mode)

        self.assertEqual(command, ["/usr/bin/codex", "app-server", "--listen", "stdio://"])
        self.assertNotIn("exec", command)

    def test_turn_sandbox_policy_carries_readable_and_writable_roots(self) -> None:
        session = _session("sandbox")
        policy = _turn_sandbox_policy(_launch_spec(session))

        self.assertEqual(policy["type"], "workspaceWrite")
        self.assertTrue(policy["networkAccess"])
        self.assertEqual(policy["readOnlyAccess"], {"type": "restricted", "includePlatformDefaults": True, "readableRoots": [session.workspace_root]})
        self.assertNotIn("readableRoots", policy)
        self.assertEqual(policy["writableRoots"], [session.workspace_root])

    def test_codex_execution_uses_persistent_app_server_thread(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name)
        emitted = []
        provider_threads = []

        result = execute_runtime_turn(
            session=session,
            provider=build_codex_definition(),
            input_text="hello",
            launch_spec=_launch_spec(session),
            event_sink=emitted.append,
            on_provider_thread_id=provider_threads.append,
            command_runner=FakeCodexProcess,
            timeout_seconds=2,
        )

        self.assertEqual(provider_threads, ["thread-1"])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output_text, "hello")
        self.assertEqual([event.event_type for event in emitted], ["runtime.output.delta"])
        self.assertEqual(emitted[0].payload["text"], "hello")
        self.assertEqual(FakeCodexProcess.requests[-3:], ["initialize", "thread/start", "turn/start"])

    def test_codex_execution_removes_provider_generated_system_skills_before_thread_start(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name, session_id="session-system-skills")
        launch_spec = _launch_spec(session)
        codex_home = Path(temp_dir.name) / "workspace" / "runtime" / "session-system-skills" / "codex-home"
        launch_spec.env_overrides["CODEX_HOME"] = str(codex_home)

        result = execute_runtime_turn(
            session=session,
            provider=build_codex_definition(),
            input_text="hello",
            launch_spec=launch_spec,
            command_runner=FakeCodexProcess,
            timeout_seconds=2,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertFalse((codex_home / "skills" / ".system").exists())
        self.assertFalse(FakeCodexProcess.system_skills_present_at_thread_start)

    def test_codex_completed_agent_message_without_delta_is_emitted(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name, session_id="session-snapshot-only")
        emitted = []

        result = execute_runtime_turn(
            session=session,
            provider=build_codex_definition(),
            input_text="hello",
            launch_spec=_launch_spec(session),
            event_sink=emitted.append,
            command_runner=FakeCodexSnapshotOnlyProcess,
            timeout_seconds=2,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output_text, "snapshot answer")
        self.assertEqual([event.event_type for event in emitted], ["runtime.output.delta"])
        self.assertEqual(emitted[0].payload["text"], "snapshot answer")

    def test_codex_execution_has_no_default_turn_timeout(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name, session_id="session-no-timeout")
        provider_threads = []

        with patch("core.runtime.execution.execute_codex_app_server_turn") as execute_turn:
            execute_turn.return_value.output_text = "done"
            execute_turn.return_value.exit_code = 0
            execute_runtime_turn(
                session=session,
                provider=build_codex_definition(),
                input_text="long task",
                launch_spec=_launch_spec(session),
                on_provider_thread_id=provider_threads.append,
            )

        self.assertIsNone(execute_turn.call_args.kwargs["timeout_seconds"])

    def test_codex_retryable_app_server_error_does_not_end_turn(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name, session_id="session-retry")
        emitted = []

        result = execute_runtime_turn(
            session=session,
            provider=build_codex_definition(),
            input_text="hello",
            launch_spec=_launch_spec(session),
            event_sink=emitted.append,
            command_runner=FakeCodexRetryProcess,
            timeout_seconds=2,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output_text, "hello after retry")
        self.assertEqual([event.event_type for event in emitted], ["runtime.step.updated", "runtime.output.delta"])

    def test_codex_terminal_app_server_error_is_returned_to_runtime(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name, session_id="session-terminal-error")

        result = execute_runtime_turn(
            session=session,
            provider=build_codex_definition(),
            input_text="hello",
            launch_spec=_launch_spec(session),
            command_runner=FakeCodexTerminalErrorProcess,
            timeout_seconds=2,
        )

        self.assertEqual(result.exit_code, 1)
        self.assertIn("401 Unauthorized", result.output_text)

    def test_codex_unknown_search_notification_is_emitted_as_generic_tool_event(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name, session_id="session-web-search")
        emitted = []

        execute_runtime_turn(
            session=session,
            provider=build_codex_definition(),
            input_text="eventi domani pisa",
            launch_spec=_launch_spec(session),
            event_sink=emitted.append,
            command_runner=FakeCodexSearchProcess,
            timeout_seconds=2,
        )

        tool_events = [event for event in emitted if event.event_type == "runtime.tool_call.started"]
        self.assertEqual(len(tool_events), 1)
        self.assertEqual(tool_events[0].payload["provider_event_type"], "web_search.started")
        self.assertEqual(tool_events[0].payload["raw"]["item"]["query"], "eventi domani pisa")


def _session(effective_mode: str, *, root: str = "/tmp", session_id: str = "session-1") -> RuntimeSessionRecord:
    now = datetime(2026, 4, 19, tzinfo=timezone.utc)
    return RuntimeSessionRecord(
        session_id=session_id,
        workspace_id="default",
        agent_id="chat",
        status="created",
        requested_mode=None,
        effective_mode=effective_mode,
        workspace_root=f"{root}/workspace",
        workdir=f"{root}/workspace",
        runtime_root=f"{root}/workspace/runtime/session-1",
        started_at=now,
        updated_at=now,
        ended_at=None,
        last_progress_at=None,
    )


def _launch_spec(session: RuntimeSessionRecord) -> RuntimeBackendLaunchSpec:
    return RuntimeBackendLaunchSpec(
        provider_id="codex",
        command=["codex", "app-server", "--listen", "stdio://"],
        env_overrides={},
        credential_binding_id=None,
        resolved_secret_refs=[],
        working_directory=session.workdir,
        execution_mode=session.effective_mode,
        readable_roots=[session.workspace_root],
        writable_roots=[session.workspace_root],
    )


class FakeStdout:
    def __init__(self) -> None:
        self.lines: queue.Queue[str | None] = queue.Queue()

    def put(self, payload: dict) -> None:
        self.lines.put(json.dumps(payload) + "\n")

    def __iter__(self):
        return self

    def __next__(self) -> str:
        try:
            line = self.lines.get(timeout=2)
        except queue.Empty:
            raise StopIteration
        if line is None:
            raise StopIteration
        return line


class FakeStdin:
    def __init__(self, stdout: FakeStdout) -> None:
        self.stdout = stdout

    def write(self, raw: str) -> None:
        payload = json.loads(raw)
        method = payload["method"]
        FakeCodexProcess.requests.append(method)
        request_id = payload["id"]
        if method == "initialize":
            if FakeCodexProcess.codex_home:
                system_root = Path(FakeCodexProcess.codex_home) / "skills" / ".system" / "imagegen"
                system_root.mkdir(parents=True, exist_ok=True)
                (system_root / "SKILL.md").write_text("# Imagegen\n", encoding="utf-8")
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "thread/start":
            if FakeCodexProcess.codex_home:
                FakeCodexProcess.system_skills_present_at_thread_start = (Path(FakeCodexProcess.codex_home) / "skills" / ".system").exists()
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": "thread-1"}}})
        elif method == "turn/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"turn": {"id": "turn-1"}}})
            self.stdout.put({"jsonrpc": "2.0", "method": "turn/started", "params": {"turn": {"id": "turn-1"}}})
            self.stdout.put({"jsonrpc": "2.0", "method": "item/agentMessage/delta", "params": {"itemId": "item-1", "delta": "hello"}})
            self.stdout.put({"jsonrpc": "2.0", "method": "item/completed", "params": {"item": {"id": "item-1", "type": "agentMessage", "text": "hello"}}})
            self.stdout.put({"jsonrpc": "2.0", "method": "turn/completed", "params": {"turn": {"status": "completed"}}})

    def flush(self) -> None:
        return


class FakeCodexProcess:
    requests: list[str] = []
    codex_home: str | None = None
    system_skills_present_at_thread_start = False

    def __init__(self, *args, **kwargs) -> None:
        FakeCodexProcess.requests = []
        FakeCodexProcess.codex_home = str(kwargs.get("env", {}).get("CODEX_HOME") or "").strip() or None
        FakeCodexProcess.system_skills_present_at_thread_start = False
        self.stdout = FakeStdout()
        self.stdin = FakeStdin(self.stdout)
        self.pid = 999999
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self):
        self.returncode = 0
        return 0


class FakeCodexSnapshotOnlyStdin(FakeStdin):
    def write(self, raw: str) -> None:
        payload = json.loads(raw)
        method = payload["method"]
        request_id = payload["id"]
        if method == "initialize":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "thread/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": "thread-snapshot"}}})
        elif method == "turn/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"turn": {"id": "turn-snapshot"}}})
            self.stdout.put({"jsonrpc": "2.0", "method": "item/completed", "params": {"item": {"id": "item-snapshot", "type": "agentMessage", "text": "snapshot answer"}}})
            self.stdout.put({"jsonrpc": "2.0", "method": "turn/completed", "params": {"turn": {"status": "completed"}}})


class FakeCodexSnapshotOnlyProcess(FakeCodexProcess):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.stdin = FakeCodexSnapshotOnlyStdin(self.stdout)


class FakeCodexRetryStdin(FakeStdin):
    def write(self, raw: str) -> None:
        payload = json.loads(raw)
        method = payload["method"]
        request_id = payload["id"]
        if method == "initialize":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "thread/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": "thread-retry"}}})
        elif method == "turn/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"turn": {"id": "turn-retry"}}})
            self.stdout.put(
                {
                    "jsonrpc": "2.0",
                    "method": "error",
                    "params": {"error": {"message": "Reconnecting... 1/5"}, "willRetry": True},
                }
            )
            self.stdout.put({"jsonrpc": "2.0", "method": "item/agentMessage/delta", "params": {"delta": "hello after retry"}})
            self.stdout.put({"jsonrpc": "2.0", "method": "turn/completed", "params": {"turn": {"status": "completed"}}})


class FakeCodexRetryProcess(FakeCodexProcess):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.stdin = FakeCodexRetryStdin(self.stdout)


class FakeCodexTerminalErrorStdin(FakeStdin):
    def write(self, raw: str) -> None:
        payload = json.loads(raw)
        method = payload["method"]
        request_id = payload["id"]
        if method == "initialize":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "thread/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": "thread-error"}}})
        elif method == "turn/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"turn": {"id": "turn-error"}}})
            self.stdout.put(
                {
                    "jsonrpc": "2.0",
                    "method": "error",
                    "params": {
                        "error": {
                            "message": "Authentication failed",
                            "additionalDetails": "unexpected status 401 Unauthorized: Missing bearer or basic authentication in header",
                        },
                        "willRetry": False,
                    },
                }
            )


class FakeCodexTerminalErrorProcess(FakeCodexProcess):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.stdin = FakeCodexTerminalErrorStdin(self.stdout)


class FakeCodexSearchStdin(FakeStdin):
    def write(self, raw: str) -> None:
        payload = json.loads(raw)
        method = payload["method"]
        request_id = payload["id"]
        if method == "initialize":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "thread/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": "thread-search"}}})
        elif method == "turn/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"turn": {"id": "turn-search"}}})
            self.stdout.put({"jsonrpc": "2.0", "method": "web_search/started", "params": {"query": "eventi domani pisa"}})
            self.stdout.put({"jsonrpc": "2.0", "method": "item/agentMessage/delta", "params": {"delta": "done"}})
            self.stdout.put({"jsonrpc": "2.0", "method": "turn/completed", "params": {"turn": {"status": "completed"}}})


class FakeCodexSearchProcess(FakeCodexProcess):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.stdin = FakeCodexSearchStdin(self.stdout)


if __name__ == "__main__":
    unittest.main()
