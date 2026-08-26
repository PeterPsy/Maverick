"""Runtime turn execution helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import subprocess
from typing import TYPE_CHECKING, Callable

from core.providers.models import ProviderDefinition, RuntimeBackendLaunchSpec
from core.providers.provider_registry import RuntimeBackendAdapter
from core.runtime.execution_events import RuntimeExecutionEvent, RuntimeExecutionEventSink, is_internal_provider_noise, parse_provider_json_event
from core.runtime.runtime_session import RuntimeSessionRecord
from core.skills.models import SkillDefinition

if TYPE_CHECKING:
    from core.providers.agentic_adapter import AgenticRuntimeEngineAdapter
    from core.runtime.provider_state import RuntimeProviderState
    from core.runtime.authority import EffectiveRuntimeAuthority


OUTPUT_DELTA_FLUSH_CHARS = 80


@dataclass(frozen=True)
class RuntimeExecutionResult:
    """Result of one runtime turn execution."""

    output_text: str
    exit_code: int
    failure_reason_code: str | None = None
    public_error_message: str | None = None
    diagnostic_reference: str | None = None


def execute_runtime_turn(
    *,
    session: RuntimeSessionRecord,
    provider: ProviderDefinition,
    input_text: str,
    invoked_skills: list[SkillDefinition] | None = None,
    timeout_seconds: int | None = None,
    event_sink: RuntimeExecutionEventSink | None = None,
    launch_spec: RuntimeBackendLaunchSpec | None = None,
    runtime_adapter: RuntimeBackendAdapter | None = None,
    agentic_adapter: AgenticRuntimeEngineAdapter | None = None,
    provider_state: RuntimeProviderState | None = None,
    correlation_id: str | None = None,
    effective_authority: EffectiveRuntimeAuthority | None = None,
    input_sources: tuple[object, ...] = (),
    on_provider_thread_id: Callable[[str], None] | None = None,
    on_provider_state_update: Callable[[dict[str, object]], RuntimeProviderState] | None = None,
    on_provider_startup_event: Callable[[str, dict[str, object]], None] | None = None,
    on_provider_turn_start_sent: Callable[[dict[str, object]], None] | None = None,
    on_provider_accepted: Callable[[dict[str, object]], None] | None = None,
    on_provider_upstream_observed: Callable[[str], None] | None = None,
    command_runner=subprocess.Popen,
) -> RuntimeExecutionResult:
    """Execute one turn through the selected provider."""
    fake_response = os.environ.get("MAVERICK_RUNTIME_FAKE_RESPONSE")
    if fake_response is not None:
        if on_provider_startup_event is not None:
            for phase in (
                "ensure_runtime_started",
                "ensure_runtime_completed",
                "ensure_thread_started",
                "ensure_thread_completed",
                "turn_start_write_started",
                "turn_start_write_sent",
            ):
                on_provider_startup_event(phase, {"provider_id": provider.provider_id, "source": "fake"})
        if on_provider_turn_start_sent is not None:
            on_provider_turn_start_sent({"provider_id": provider.provider_id, "source": "fake"})
        if on_provider_accepted is not None:
            on_provider_accepted({"provider_id": provider.provider_id, "source": "fake"})
        _emit_fake_events(event_sink)
        return RuntimeExecutionResult(output_text=fake_response, exit_code=0)

    if agentic_adapter is not None and session.execution_binding is not None:
        if provider_state is None:
            raise ValueError("Agentic adapter execution requires runtime provider state.")
        if effective_authority is None:
            raise ValueError("Agentic adapter execution requires effective runtime authority.")
        from core.runtime.agentic_execution import execute_agentic_runtime_turn
        from core.runtime.async_runtime import run_runtime_coroutine

        coalesced_sink = RuntimeOutputDeltaCoalescer(event_sink)
        try:
            return run_runtime_coroutine(
                execute_agentic_runtime_turn(
                    session=session,
                    provider_state=provider_state,
                    adapter=agentic_adapter,
                    input_text=input_text,
                    correlation_id=correlation_id or session.session_id,
                    effective_authority=effective_authority,
                    input_sources=input_sources,
                    invoked_skills=invoked_skills,
                    timeout_seconds=timeout_seconds,
                    event_sink=coalesced_sink.emit,
                    local_launch_spec=launch_spec,
                    on_provider_thread_id=on_provider_thread_id,
                    on_provider_state_update=on_provider_state_update,
                    on_provider_startup_event=on_provider_startup_event,
                    on_provider_turn_start_sent=on_provider_turn_start_sent,
                    on_provider_accepted=on_provider_accepted,
                    on_provider_upstream_observed=on_provider_upstream_observed,
                )
            )
        finally:
            coalesced_sink.flush()
    if runtime_adapter is None:
        return RuntimeExecutionResult(
            output_text=f"Provider `{provider.provider_id}` is registered but has no executable adapter in this host yet.",
            exit_code=1,
            failure_reason_code="provider_adapter_unavailable",
            public_error_message="The selected runtime adapter is unavailable.",
        )
    active_launch_spec = launch_spec or runtime_adapter.build_launch_spec(session)
    coalesced_sink = RuntimeOutputDeltaCoalescer(event_sink)
    try:
        execution_kwargs = dict(
            session=session,
            launch_spec=active_launch_spec,
            input_text=input_text,
            event_sink=coalesced_sink.emit,
            timeout_seconds=timeout_seconds,
            on_provider_thread_id=on_provider_thread_id,
            on_provider_startup_event=on_provider_startup_event,
            on_provider_turn_start_sent=on_provider_turn_start_sent,
            on_provider_accepted=on_provider_accepted,
            command_runner=command_runner,
        )
        if invoked_skills:
            execution_kwargs["invoked_skills"] = invoked_skills
        result = runtime_adapter.execute_turn(**execution_kwargs)
    finally:
        coalesced_sink.flush()
    return RuntimeExecutionResult(
        output_text=result.output_text,
        exit_code=result.exit_code,
        failure_reason_code=getattr(result, "failure_reason_code", None),
        public_error_message=getattr(result, "public_error_message", None),
        diagnostic_reference=getattr(result, "diagnostic_reference", None),
    )


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
    raw_events = os.environ.get("MAVERICK_RUNTIME_FAKE_EVENTS", "").strip()
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
