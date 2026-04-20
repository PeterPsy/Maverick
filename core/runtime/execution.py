"""Runtime turn execution helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from core.providers.codex_app_server import execute_codex_app_server_turn
from core.providers.models import ProviderDefinition, RuntimeBackendLaunchSpec
from core.runtime.execution_events import RuntimeExecutionEvent, RuntimeExecutionEventSink, is_internal_provider_noise, parse_provider_json_event
from core.runtime.runtime_session import RuntimeSessionRecord


OUTPUT_DELTA_FLUSH_CHARS = 80


@dataclass(frozen=True)
class RuntimeExecutionResult:
    """Result of one runtime turn execution."""

    output_text: str
    exit_code: int


def _codex_executable() -> str:
    configured = os.environ.get("MAVERICK3_CODEX_COMMAND", "").strip()
    if configured:
        return configured
    resolved = shutil.which("codex")
    if resolved:
        return resolved
    return "codex"


def _codex_app_server_command(*, execution_mode: str, codex_command: str | None = None) -> list[str]:
    """Return the canonical Codex app-server command for interactive sessions."""
    command = [str(codex_command or "").strip() or _codex_executable()]
    command.extend(["app-server", "--listen", "stdio://"])
    return command


def _fallback_launch_spec(session: RuntimeSessionRecord) -> RuntimeBackendLaunchSpec:
    """Build a fallback launch spec for tests that call execution directly."""
    env = dict(os.environ)
    command = _codex_app_server_command(execution_mode=session.effective_mode)
    path_entries = [entry for entry in str(env.get("PATH") or "").split(os.pathsep) if entry]
    prepend: list[str] = []
    executable = command[0]
    if os.sep in executable:
        prepend.append(str(Path(executable).parent))
    node = shutil.which("node")
    if node:
        prepend.append(str(Path(node).parent))
    merged: list[str] = []
    seen: set[str] = set()
    for entry in [*prepend, *path_entries]:
        if entry and entry not in seen:
            seen.add(entry)
            merged.append(entry)
    if merged:
        env["PATH"] = os.pathsep.join(merged)
    runtime_home = Path(session.runtime_root) / "codex-home"
    runtime_home.mkdir(parents=True, exist_ok=True)
    env["CODEX_HOME"] = str(runtime_home)
    env["MAVERICK_WORKSPACE_ROOT"] = session.workspace_root
    env["MAVERICK_RUNTIME_ROOT"] = session.runtime_root
    if session.effective_mode == "sandbox":
        env["TMPDIR"] = session.runtime_root
        env["TMP"] = session.runtime_root
        env["TEMP"] = session.runtime_root
    return RuntimeBackendLaunchSpec(
        provider_id="codex",
        command=command,
        env_overrides=env,
        credential_binding_id=None,
        resolved_secret_refs=[],
        working_directory=session.workdir,
        execution_mode=session.effective_mode,
        readable_roots=["/"] if session.effective_mode == "full-access" else [session.workspace_root],
        writable_roots=["/"] if session.effective_mode == "full-access" else [session.workspace_root],
    )


def execute_runtime_turn(
    *,
    session: RuntimeSessionRecord,
    provider: ProviderDefinition,
    input_text: str,
    timeout_seconds: int | None = None,
    event_sink: RuntimeExecutionEventSink | None = None,
    launch_spec: RuntimeBackendLaunchSpec | None = None,
    on_provider_thread_id: Callable[[str], None] | None = None,
    command_runner=subprocess.Popen,
) -> RuntimeExecutionResult:
    """Execute one turn through the selected provider."""
    fake_response = os.environ.get("MAVERICK3_RUNTIME_FAKE_RESPONSE")
    if fake_response is not None:
        _emit_fake_events(event_sink)
        return RuntimeExecutionResult(output_text=fake_response, exit_code=0)

    if provider.provider_id != "codex":
        return RuntimeExecutionResult(
            output_text=f"Provider `{provider.provider_id}` is registered but has no executable adapter in this host yet.",
            exit_code=1,
        )

    Path(session.workdir).mkdir(parents=True, exist_ok=True)
    Path(session.runtime_root).mkdir(parents=True, exist_ok=True)
    coalesced_sink = RuntimeOutputDeltaCoalescer(event_sink)
    try:
        result = execute_codex_app_server_turn(
            session=session,
            launch_spec=launch_spec or _fallback_launch_spec(session),
            input_text=input_text,
            event_sink=coalesced_sink.emit,
            timeout_seconds=timeout_seconds,
            on_provider_thread_id=on_provider_thread_id,
            command_runner=command_runner,
        )
    finally:
        coalesced_sink.flush()
    return RuntimeExecutionResult(output_text=result.output_text, exit_code=result.exit_code)


class RuntimeOutputDeltaCoalescer:
    """Coalesce tiny output deltas before they reach persistence and transport."""

    def __init__(
        self,
        event_sink: RuntimeExecutionEventSink | None,
        *,
        flush_chars: int = OUTPUT_DELTA_FLUSH_CHARS,
    ) -> None:
        self.event_sink = event_sink
        self.flush_chars = flush_chars
        self._chunks: list[str] = []
        self._pending_chars = 0
        self._payload_template: dict[str, object] = {}

    def emit(self, event: RuntimeExecutionEvent) -> None:
        """Emit one event, buffering adjacent output deltas."""
        if self.event_sink is None:
            return
        if event.event_type != "runtime.output.delta":
            self.flush()
            self.event_sink(event)
            return
        text = str(event.payload.get("text") or "")
        if not text:
            return
        if not self._chunks:
            self._payload_template = {key: value for key, value in event.payload.items() if key != "text"}
        self._chunks.append(text)
        self._pending_chars += len(text)
        if self._pending_chars >= self.flush_chars:
            self.flush()

    def flush(self) -> None:
        """Emit buffered output text as one runtime delta event."""
        if self.event_sink is None or not self._chunks:
            return
        text = "".join(self._chunks)
        payload = {**self._payload_template, "text": text}
        self._chunks = []
        self._pending_chars = 0
        self._payload_template = {}
        self.event_sink(RuntimeExecutionEvent(event_type="runtime.output.delta", payload=payload))


def _record_process_line(
    *,
    line: str,
    is_stderr: bool,
    stdout_lines: list[str],
    stderr_lines: list[str],
    event_sink: RuntimeExecutionEventSink | None,
) -> None:
    """Normalize one raw provider line.

    Kept for parser tests and one-shot diagnostic tooling; product chat uses the
    Codex app-server path above.
    """
    if is_internal_provider_noise(line):
        return
    event = parse_provider_json_event(line)
    if is_stderr:
        stderr_lines.append(line)
    else:
        stdout_lines.append(line)
    if event is not None and event_sink is not None:
        event_sink(event)
        return
    if is_stderr and event_sink is not None and line.strip():
        event_sink(RuntimeExecutionEvent(event_type="runtime.step.updated", payload={"label": line.strip(), "source": "stderr"}))


def _emit_fake_events(event_sink: RuntimeExecutionEventSink | None) -> None:
    if event_sink is None:
        return
    raw_events = os.environ.get("MAVERICK3_RUNTIME_FAKE_EVENTS", "").strip()
    if not raw_events:
        return
    try:
        events = json.loads(raw_events)
    except json.JSONDecodeError:
        return
    if not isinstance(events, list):
        return
    for item in events:
        if not isinstance(item, dict):
            continue
        event_type = str(item.get("event_type") or "").strip()
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        if event_type:
            event_sink(RuntimeExecutionEvent(event_type=event_type, payload=payload))


__all__ = ["RuntimeExecutionResult", "execute_runtime_turn"]
