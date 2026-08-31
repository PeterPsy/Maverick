import os
import json
from pathlib import Path
import queue
from types import SimpleNamespace
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from core.providers.models import ProviderCapabilitySet, ProviderDefinition, RuntimeBackendLaunchSpec
from core.providers.provider_codex import CodexProviderAdapter, build_codex_definition
from core.providers.provider_codex import _codex_app_server_command
from core.providers.codex_app_server import _turn_sandbox_policy, prewarm_codex_app_server_runtime
from core.providers.codex_app_server_runtime_errors import (
    codex_error_info,
    codex_terminal_failure_reason_code,
)
from core.providers.provider_registry import ProviderRegistry
from core.providers.service import configure_workspace_provider
from core.providers.store import ProviderDocumentStore, ProviderCollections
from core.runtime.execution import execute_runtime_turn
from core.runtime.execution import RuntimeExecutionResult
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.turn_submission import interrupt_runtime_provider_turn
from tests.support.collections import FakeCollection


class RuntimeExecutionCommandTest(unittest.TestCase):
    def test_sandbox_session_uses_codex_app_server_without_legacy_landlock_flag(self) -> None:
        with patch.dict(os.environ, {"MAVERICK_CODEX_COMMAND": "/usr/bin/codex"}, clear=False):
            command = _codex_app_server_command(execution_mode=_session("sandbox").effective_mode)

        self.assertEqual(command, ["/usr/bin/codex", "app-server", "--listen", "stdio://"])
        self.assertNotIn("exec", command)

    def test_full_access_session_uses_codex_app_server_without_landlock_flag(self) -> None:
        with patch.dict(os.environ, {"MAVERICK_CODEX_COMMAND": "/usr/bin/codex"}, clear=False):
            command = _codex_app_server_command(execution_mode=_session("full-access").effective_mode)

        self.assertEqual(command, ["/usr/bin/codex", "app-server", "--listen", "stdio://"])
        self.assertNotIn("exec", command)

    def test_turn_sandbox_policy_uses_current_codex_workspace_write_shape(self) -> None:
        session = _session("sandbox")
        policy = _turn_sandbox_policy(_launch_spec(session))

        self.assertEqual(policy["type"], "workspaceWrite")
        self.assertTrue(policy["networkAccess"])
        self.assertFalse(policy["excludeTmpdirEnvVar"])
        self.assertFalse(policy["excludeSlashTmp"])
        self.assertNotIn("readOnlyAccess", policy)
        self.assertNotIn("readableRoots", policy)
        self.assertEqual(policy["writableRoots"], [session.workspace_root])

    def test_codex_execution_uses_persistent_app_server_thread(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name)
        emitted = []
        provider_threads = []
        startup_events = []

        result = execute_runtime_turn(
            session=session,
            provider=build_codex_definition(),
            input_text="hello",
            launch_spec=_launch_spec(session),
            runtime_adapter=_codex_adapter(),
            event_sink=emitted.append,
            on_provider_thread_id=provider_threads.append,
            on_provider_startup_event=lambda phase, metadata: startup_events.append((phase, metadata)),
            command_runner=FakeCodexProcess,
            timeout_seconds=2,
        )

        self.assertEqual(provider_threads, ["thread-1"])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output_text, "hello")
        self.assertEqual([event.event_type for event in emitted], ["runtime.output.delta"])
        self.assertEqual(emitted[0].payload["text"], "hello")
        self.assertEqual(FakeCodexProcess.requests[-3:], ["initialize", "thread/start", "turn/start"])
        self.assertEqual(
            [phase for phase, _metadata in startup_events],
            [
                "ensure_runtime_started",
                "ensure_runtime_completed",
                "remove_generated_skills_started",
                "remove_generated_skills_completed",
                "ensure_thread_started",
                "ensure_thread_completed",
                "event_sink_reset_started",
                "event_sink_reset_completed",
                "turn_start_write_started",
                "turn_start_write_sent",
            ],
        )
        self.assertGreaterEqual(startup_events[1][1]["ensure_runtime_ms"], 0)
        self.assertGreaterEqual(startup_events[3][1]["remove_generated_skills_ms"], 0)
        self.assertGreaterEqual(startup_events[5][1]["ensure_provider_thread_ms"], 0)
        self.assertGreaterEqual(startup_events[7][1]["event_sink_reset_ms"], 0)

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
            runtime_adapter=_codex_adapter(),
            command_runner=FakeCodexProcess,
            timeout_seconds=2,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertFalse((codex_home / "skills" / ".system").exists())
        self.assertFalse(FakeCodexProcess.system_skills_present_at_thread_start)

    def test_codex_prewarm_starts_runtime_thread_before_turn(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name, session_id="session-prewarm")
        launch_spec = _launch_spec(session)

        provider_thread_id = prewarm_codex_app_server_runtime(
            session=session,
            launch_spec=launch_spec,
            command_runner=FakeCodexProcess,
        )

        self.assertEqual(provider_thread_id, "thread-1")
        self.assertEqual(FakeCodexProcess.requests, ["initialize", "thread/start"])

        result = execute_runtime_turn(
            session=session,
            provider=build_codex_definition(),
            input_text="hello",
            launch_spec=launch_spec,
            runtime_adapter=_codex_adapter(),
            command_runner=FakeCodexProcess,
            timeout_seconds=2,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(FakeCodexProcess.requests, ["initialize", "thread/start", "turn/start"])

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
            runtime_adapter=_codex_adapter(),
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

        with patch("core.providers.codex_app_server.execute_codex_app_server_turn") as execute_turn:
            execute_turn.return_value.output_text = "done"
            execute_turn.return_value.exit_code = 0
            execute_runtime_turn(
                session=session,
                provider=build_codex_definition(),
                input_text="long task",
                launch_spec=_launch_spec(session),
                runtime_adapter=_codex_adapter(),
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
            runtime_adapter=_codex_adapter(),
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
            runtime_adapter=_codex_adapter(),
            command_runner=FakeCodexTerminalErrorProcess,
            timeout_seconds=2,
        )

        self.assertEqual(result.exit_code, 1)
        self.assertIn("401 Unauthorized", result.output_text)

    def test_codex_overload_is_structured_and_does_not_publish_raw_error_step(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name, session_id="session-overloaded")
        emitted = []

        result = execute_runtime_turn(
            session=session,
            provider=build_codex_definition(),
            input_text="continue the implementation",
            launch_spec=_launch_spec(session),
            runtime_adapter=_codex_adapter(),
            event_sink=emitted.append,
            command_runner=FakeCodexOverloadedProcess,
            timeout_seconds=2,
        )

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.output_text, "work already completed")
        self.assertEqual(result.failure_reason_code, "provider_overloaded")
        self.assertIn("completed actions are preserved", result.public_error_message)
        self.assertEqual(
            [event.event_type for event in emitted],
            ["runtime.output.delta"],
        )
        self.assertNotIn("Codex app-server error", repr(emitted))
        self.assertNotIn("serverOverloaded", repr(emitted))

    def test_codex_cyber_policy_block_is_structured_and_redaction_safe(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name, session_id="session-policy-blocked")
        emitted = []

        result = execute_runtime_turn(
            session=session,
            provider=build_codex_definition(),
            input_text="review the defensive security implementation",
            launch_spec=_launch_spec(session),
            runtime_adapter=_codex_adapter(),
            event_sink=emitted.append,
            command_runner=FakeCodexCyberPolicyProcess,
            timeout_seconds=2,
        )

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.output_text, "security review partially completed")
        self.assertEqual(
            result.failure_reason_code,
            "provider_cybersecurity_policy_blocked",
        )
        self.assertIn("cybersecurity policy", result.public_error_message)
        self.assertIn("Rephrase", result.public_error_message)
        self.assertNotIn("chatgpt.com/cyber", result.public_error_message)
        self.assertEqual(
            [event.event_type for event in emitted],
            ["runtime.output.delta"],
        )
        self.assertNotIn("Codex app-server error", repr(emitted))
        self.assertNotIn("cyberPolicy", repr(emitted))
        self.assertNotIn("chatgpt.com/cyber", repr(emitted))

    def test_codex_cyber_policy_category_aliases_share_one_failure_code(self) -> None:
        for error_info in ("cyberPolicy", "cyber_policy"):
            with self.subTest(error_info=error_info):
                self.assertEqual(
                    codex_terminal_failure_reason_code(error_info),
                    "provider_cybersecurity_policy_blocked",
                )
        self.assertEqual(
            codex_terminal_failure_reason_code("unknownPrivateCategory"),
            "provider_execution_failed",
        )

    def test_codex_error_info_accepts_both_protocol_key_spellings(self) -> None:
        for key, value in (
            ("codexErrorInfo", "cyberPolicy"),
            ("codex_error_info", "cyber_policy"),
        ):
            with self.subTest(key=key):
                self.assertEqual(
                    codex_error_info({"error": {key: value}}),
                    value,
                )

    def test_codex_process_exit_before_turn_completed_unblocks_execution(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name, session_id="session-process-exit")

        result = execute_runtime_turn(
            session=session,
            provider=build_codex_definition(),
            input_text="hello",
            launch_spec=_launch_spec(session),
            runtime_adapter=_codex_adapter(),
            command_runner=FakeCodexDiesBeforeCompletionProcess,
            timeout_seconds=2,
        )

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Codex app-server stream ended before turn completion", result.output_text)

    def test_codex_command_output_delta_notifications_are_filtered(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name, session_id="session-command-output-delta")
        emitted = []

        result = execute_runtime_turn(
            session=session,
            provider=build_codex_definition(),
            input_text="hello",
            launch_spec=_launch_spec(session),
            runtime_adapter=_codex_adapter(),
            event_sink=emitted.append,
            command_runner=FakeCodexCommandOutputDeltaProcess,
            timeout_seconds=2,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output_text, "done")
        self.assertEqual(
            [event.event_type for event in emitted],
            ["runtime.tool_call.started", "runtime.tool_call.completed", "runtime.output.delta"],
        )
        self.assertNotIn(
            "item/commandExecution/outputDelta",
            [event.payload.get("provider_event_type") for event in emitted],
        )

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
            runtime_adapter=_codex_adapter(),
            event_sink=emitted.append,
            command_runner=FakeCodexSearchProcess,
            timeout_seconds=2,
        )

        tool_events = [event for event in emitted if event.event_type == "runtime.tool_call.started"]
        self.assertEqual(len(tool_events), 1)
        self.assertEqual(tool_events[0].payload["provider_event_type"], "web_search.started")
        self.assertEqual(tool_events[0].payload["raw"]["item"]["query"], "eventi domani pisa")

    def test_codex_app_cli_chat_render_output_is_emitted_as_structured_runtime_output(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name, session_id="session-chat-render")
        emitted = []

        result = execute_runtime_turn(
            session=session,
            provider=build_codex_definition(),
            input_text="create a dynamic view",
            launch_spec=_launch_spec(session),
            runtime_adapter=_codex_adapter(),
            event_sink=emitted.append,
            command_runner=FakeCodexChatRenderCliProcess,
            timeout_seconds=2,
        )

        structured_events = [event for event in emitted if event.event_type == "runtime.output.structured"]
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(len(structured_events), 1)
        self.assertEqual(structured_events[0].payload["structured_content"]["kind"], "dynamic.view.instance")
        self.assertEqual(structured_events[0].payload["structured_content"]["payload"]["id"], "view_1")

    def test_codex_completed_agent_message_can_emit_structured_runtime_output(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = _session("sandbox", root=temp_dir.name, session_id="session-agent-structured")
        emitted = []

        result = execute_runtime_turn(
            session=session,
            provider=build_codex_definition(),
            input_text="show checklist",
            launch_spec=_launch_spec(session),
            runtime_adapter=_codex_adapter(),
            event_sink=emitted.append,
            command_runner=FakeCodexStructuredAgentMessageProcess,
            timeout_seconds=2,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output_text, "Checklist pronta")
        self.assertEqual([event.event_type for event in emitted], ["runtime.output.delta", "runtime.output.structured"])
        self.assertEqual(emitted[0].payload["text"], "Checklist pronta")
        self.assertEqual(emitted[1].payload["structured_content"]["kind"], "checklist.design")
        self.assertEqual(emitted[1].payload["structured_content"]["payload"]["id"], "check_demo1234")

    def test_runtime_execution_delegates_non_codex_providers_to_adapter(self) -> None:
        session = _session("sandbox", session_id="session-fake-provider")
        emitted = []
        adapter = FakeRuntimeAdapter()

        result = execute_runtime_turn(
            session=session,
            provider=adapter.provider_definition(),
            input_text="hello adapter",
            launch_spec=adapter.build_launch_spec(session),
            runtime_adapter=adapter,
            event_sink=emitted.append,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output_text, "fake: hello adapter")
        self.assertEqual(adapter.inputs, ["hello adapter"])
        self.assertEqual([event.event_type for event in emitted], ["runtime.output.delta"])
        self.assertEqual(emitted[0].payload["text"], "fake: hello adapter")

    def test_runtime_interrupt_delegates_non_codex_providers_to_adapter(self) -> None:
        provider_store = ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )
        registry = ProviderRegistry()
        adapter = FakeRuntimeAdapter()
        registry.register_runtime_adapter(adapter)
        configure_workspace_provider(provider_store, workspace_id="default", provider_id="fake-runtime", registry=registry)
        session = _session("sandbox", session_id="session-fake-interrupt")

        interrupted = interrupt_runtime_provider_turn(
            SimpleNamespace(provider_store=provider_store),
            session,
            registry=registry,
        )

        self.assertTrue(interrupted)
        self.assertEqual(adapter.interrupted_sessions, ["session-fake-interrupt"])

    def test_runtime_interrupt_surfaces_do_not_import_codex_app_server(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        for relative_path in ["core/api/runtime_api.py", "core/apps/runtime_requests.py"]:
            source = (repo_root / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("codex_app_server", source, relative_path)
            self.assertNotIn("interrupt_codex_app_server_turn", source, relative_path)


def _session(effective_mode: str, *, root: str = "/tmp", session_id: str = "session-1") -> RuntimeSessionRecord:
    now = datetime(2026, 4, 19, tzinfo=timezone.utc)
    return RuntimeSessionRecord(
        session_id=session_id,
        workspace_id="default",
        agent_id="runtime-agent",
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


def _codex_adapter() -> CodexProviderAdapter:
    return CodexProviderAdapter(codex_command="codex")


class FakeRuntimeAdapter:
    def __init__(self) -> None:
        self.inputs: list[str] = []
        self.interrupted_sessions: list[str] = []

    def provider_definition(self) -> ProviderDefinition:
        return ProviderDefinition(
            provider_id="fake-runtime",
            label="Fake Runtime",
            description="Test runtime adapter.",
            kind="runtime_backend",
            status="active",
            capabilities=ProviderCapabilitySet(
                supports_interactive_runtime=True,
                supports_streaming=True,
                supports_tools=True,
                supports_mcp=False,
                supports_skills=False,
                supports_filesystem_access=True,
                supports_remote_execution=False,
                supports_api_key_auth=False,
                supports_local_binary=False,
            ),
            default_model_family=None,
            requires_credentials=False,
            supported_execution_modes=["sandbox"],
            created_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
            updated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        )

    def validate_backend(self) -> None:
        return

    def build_launch_spec(self, session: RuntimeSessionRecord, **_kwargs) -> RuntimeBackendLaunchSpec:
        return RuntimeBackendLaunchSpec(
            provider_id="fake-runtime",
            command=["fake-runtime"],
            env_overrides={},
            credential_binding_id=None,
            resolved_secret_refs=[],
            working_directory=session.workdir,
            execution_mode=session.effective_mode,
            readable_roots=[session.workspace_root],
            writable_roots=[session.workspace_root],
        )

    def prepare_runtime_skills(self, session: RuntimeSessionRecord, skills: list) -> list:
        return []

    def execute_turn(
        self,
        *,
        session: RuntimeSessionRecord,
        launch_spec: RuntimeBackendLaunchSpec,
        input_text: str,
        event_sink=None,
        timeout_seconds: int | None = None,
        on_provider_thread_id=None,
        on_provider_startup_event=None,
        on_provider_turn_start_sent=None,
        on_provider_accepted=None,
        command_runner=None,
    ) -> RuntimeExecutionResult:
        self.inputs.append(input_text)
        output = f"fake: {input_text}"
        if on_provider_startup_event is not None:
            on_provider_startup_event("turn_start_write_started", {"provider_id": "fake-runtime", "source": "fake"})
        if on_provider_turn_start_sent is not None:
            on_provider_turn_start_sent({"provider_id": "fake-runtime", "source": "fake"})
        if on_provider_accepted is not None:
            on_provider_accepted({"provider_id": "fake-runtime", "source": "fake"})
        if event_sink is not None:
            event_sink(RuntimeExecutionEvent(event_type="runtime.output.delta", payload={"text": output}))
        return RuntimeExecutionResult(output_text=output, exit_code=0)

    def close_runtime(self, session_id: str) -> None:
        return

    def interrupt_turn(self, session_id: str) -> bool:
        self.interrupted_sessions.append(session_id)
        return True

    def build_recovery_command(self, **_kwargs) -> list[str]:
        return ["fake-runtime"]


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


class FakeCodexOverloadedStdin(FakeStdin):
    output_text = "work already completed"
    error_message = "Selected model is at capacity. Please try a different model."
    error_info = "serverOverloaded"

    def write(self, raw: str) -> None:
        payload = json.loads(raw)
        method = payload["method"]
        request_id = payload["id"]
        if method == "initialize":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "thread/start":
            self.stdout.put(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"thread": {"id": "thread-overloaded"}},
                }
            )
        elif method == "turn/start":
            self.stdout.put(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"turn": {"id": "turn-overloaded"}},
                }
            )
            self.stdout.put(
                {
                    "jsonrpc": "2.0",
                    "method": "item/agentMessage/delta",
                    "params": {
                        "itemId": "item-overloaded",
                        "delta": self.output_text,
                    },
                }
            )
            self.stdout.put(
                {
                    "jsonrpc": "2.0",
                    "method": "error",
                    "params": {
                        "error": {
                            "message": self.error_message,
                            "codexErrorInfo": self.error_info,
                            "additionalDetails": None,
                        },
                        "willRetry": False,
                    },
                }
            )
            self.stdout.put(
                {
                    "jsonrpc": "2.0",
                    "method": "turn/completed",
                    "params": {
                        "turn": {
                            "id": "turn-overloaded",
                            "status": "failed",
                        }
                    },
                }
            )


class FakeCodexOverloadedProcess(FakeCodexProcess):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.stdin = FakeCodexOverloadedStdin(self.stdout)


class FakeCodexCyberPolicyStdin(FakeCodexOverloadedStdin):
    output_text = "security review partially completed"
    error_message = (
        "This content was flagged for possible cybersecurity risk. "
        "Join the authorized program at https://chatgpt.com/cyber."
    )
    error_info = "cyberPolicy"


class FakeCodexCyberPolicyProcess(FakeCodexProcess):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.stdin = FakeCodexCyberPolicyStdin(self.stdout)


class FakeCodexDiesBeforeCompletionStdin(FakeStdin):
    def __init__(self, stdout: FakeStdout, process: FakeCodexProcess) -> None:
        super().__init__(stdout)
        self.process = process

    def write(self, raw: str) -> None:
        payload = json.loads(raw)
        method = payload["method"]
        request_id = payload["id"]
        if method == "initialize":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "thread/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": "thread-dead"}}})
        elif method == "turn/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"turn": {"id": "turn-dead"}}})
            self.stdout.put({"jsonrpc": "2.0", "method": "turn/started", "params": {"turn": {"id": "turn-dead"}}})
            self.process.returncode = -15
            self.stdout.lines.put(None)


class FakeCodexDiesBeforeCompletionProcess(FakeCodexProcess):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.stdin = FakeCodexDiesBeforeCompletionStdin(self.stdout, self)


class FakeCodexCommandOutputDeltaStdin(FakeStdin):
    def write(self, raw: str) -> None:
        payload = json.loads(raw)
        method = payload["method"]
        request_id = payload["id"]
        if method == "initialize":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "thread/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": "thread-command-delta"}}})
        elif method == "turn/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"turn": {"id": "turn-command-delta"}}})
            self.stdout.put(
                {
                    "jsonrpc": "2.0",
                    "method": "item/started",
                    "params": {
                        "item": {
                            "id": "cmd-delta",
                            "type": "commandExecution",
                            "command": "python -c 'print(\"x\")'",
                        }
                    },
                }
            )
            self.stdout.put(
                {
                    "jsonrpc": "2.0",
                    "method": "item/commandExecution/outputDelta",
                    "params": {
                        "threadId": "thread-command-delta",
                        "turnId": "turn-command-delta",
                        "itemId": "cmd-delta",
                        "delta": "x\n" * 10_000,
                    },
                }
            )
            self.stdout.put(
                {
                    "jsonrpc": "2.0",
                    "method": "item/completed",
                    "params": {
                        "item": {
                            "id": "cmd-delta",
                            "type": "commandExecution",
                            "command": "python -c 'print(\"x\")'",
                            "exitCode": 0,
                            "aggregatedOutput": "x\n",
                        }
                    },
                }
            )
            self.stdout.put({"jsonrpc": "2.0", "method": "item/agentMessage/delta", "params": {"delta": "done"}})
            self.stdout.put({"jsonrpc": "2.0", "method": "turn/completed", "params": {"turn": {"status": "completed"}}})


class FakeCodexCommandOutputDeltaProcess(FakeCodexProcess):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.stdin = FakeCodexCommandOutputDeltaStdin(self.stdout)


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


class FakeCodexChatRenderCliStdin(FakeStdin):
    def write(self, raw: str) -> None:
        payload = json.loads(raw)
        method = payload["method"]
        request_id = payload["id"]
        if method == "initialize":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "thread/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": "thread-chat-render"}}})
        elif method == "turn/start":
            cli_output = json.dumps(
                {
                    "status_code": 200,
                    "chat_render": {
                        "kind": "dynamic.view.instance",
                        "payload": {"id": "view_1", "title": "Storage chart"},
                    },
                }
            )
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"turn": {"id": "turn-chat-render"}}})
            self.stdout.put(
                {
                    "jsonrpc": "2.0",
                    "method": "item/completed",
                    "params": {
                        "item": {
                            "id": "cmd_1",
                            "type": "commandExecution",
                            "command": "app.sample-view.sample-view",
                            "exitCode": 0,
                            "aggregatedOutput": cli_output,
                        }
                    },
                }
            )
            self.stdout.put({"jsonrpc": "2.0", "method": "item/agentMessage/delta", "params": {"delta": cli_output}})
            self.stdout.put({"jsonrpc": "2.0", "method": "turn/completed", "params": {"turn": {"status": "completed"}}})


class FakeCodexChatRenderCliProcess(FakeCodexProcess):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.stdin = FakeCodexChatRenderCliStdin(self.stdout)


class FakeCodexStructuredAgentMessageStdin(FakeStdin):
    def write(self, raw: str) -> None:
        payload = json.loads(raw)
        method = payload["method"]
        request_id = payload["id"]
        if method == "initialize":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "thread/start":
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": "thread-structured"}}})
        elif method == "turn/start":
            agent_output = json.dumps(
                {
                    "text": "Checklist pronta",
                    "structured_content": {
                        "kind": "checklist.design",
                        "payload": {"id": "check_demo1234", "title": "Checklist demo"},
                    },
                }
            )
            self.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": {"turn": {"id": "turn-structured"}}})
            self.stdout.put({"jsonrpc": "2.0", "method": "item/agentMessage/delta", "params": {"itemId": "item-structured", "delta": agent_output[:24]}})
            self.stdout.put({"jsonrpc": "2.0", "method": "item/agentMessage/delta", "params": {"itemId": "item-structured", "delta": agent_output[24:]}})
            self.stdout.put(
                {
                    "jsonrpc": "2.0",
                    "method": "item/completed",
                    "params": {"item": {"id": "item-structured", "type": "agentMessage", "text": agent_output}},
                }
            )
            self.stdout.put({"jsonrpc": "2.0", "method": "turn/completed", "params": {"turn": {"status": "completed"}}})


class FakeCodexStructuredAgentMessageProcess(FakeCodexProcess):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.stdin = FakeCodexStructuredAgentMessageStdin(self.stdout)


if __name__ == "__main__":
    unittest.main()
