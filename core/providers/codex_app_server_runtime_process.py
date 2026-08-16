"""Stateful Codex app-server protocol client."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import subprocess
import time
from typing import Callable

from core.providers.codex_skill_inputs import codex_skill_input_items
from core.providers.models import RuntimeBackendLaunchSpec
from core.providers.codex_app_server_runtime_state import _RUNTIMES, _RUNTIMES_LOCK
from core.runtime.execution_events import RuntimeExecutionEventSink
from core.runtime.process_control import terminate_runtime_process, unregister_runtime_process
from core.runtime.runtime_session import RuntimeSessionRecord
from core.skills.models import SkillDefinition


@dataclass
class CodexAppServerTurnResult:
    """Result of one Codex app-server turn."""

    output_text: str
    exit_code: int
    provider_thread_id: str


def prewarm_codex_app_server_runtime(
    *,
    session: RuntimeSessionRecord,
    launch_spec: RuntimeBackendLaunchSpec,
    command_runner=subprocess.Popen,
) -> str:
    """Start the Codex app-server and bind a provider thread before the next turn."""
    runtime = _ensure_runtime(session=session, launch_spec=launch_spec, command_runner=command_runner)
    _remove_generated_system_skills_if_needed(runtime=runtime, launch_spec=launch_spec, session=session)
    return _ensure_provider_thread(runtime=runtime, session=session, launch_spec=launch_spec, on_provider_thread_id=None)



def execute_codex_app_server_turn(
    *,
    session: RuntimeSessionRecord,
    launch_spec: RuntimeBackendLaunchSpec,
    input_text: str,
    invoked_skills: list[SkillDefinition] | None = None,
    event_sink: RuntimeExecutionEventSink | None,
    timeout_seconds: int | None,
    on_provider_thread_id: Callable[[str], None] | None = None,
    on_provider_startup_event: Callable[[str, dict[str, object]], None] | None = None,
    on_provider_turn_start_sent: Callable[[dict[str, object]], None] | None = None,
    on_provider_accepted: Callable[[dict[str, object]], None] | None = None,
    command_runner=subprocess.Popen,
) -> CodexAppServerTurnResult:
    """Execute one turn against a persistent Codex app-server thread."""
    if on_provider_startup_event is not None:
        on_provider_startup_event("ensure_runtime_started", {})
    ensure_runtime_started_at = time.perf_counter()
    runtime = _ensure_runtime(session=session, launch_spec=launch_spec, command_runner=command_runner)
    ensure_runtime_ms = (time.perf_counter() - ensure_runtime_started_at) * 1000
    if on_provider_startup_event is not None:
        on_provider_startup_event("ensure_runtime_completed", {"ensure_runtime_ms": ensure_runtime_ms})
    if on_provider_startup_event is not None:
        on_provider_startup_event("remove_generated_skills_started", {})
    remove_generated_skills_started_at = time.perf_counter()
    generated_skills_removed = _remove_generated_system_skills_if_needed(
        runtime=runtime,
        launch_spec=launch_spec,
        session=session,
    )
    remove_generated_skills_ms = (time.perf_counter() - remove_generated_skills_started_at) * 1000
    if on_provider_startup_event is not None:
        on_provider_startup_event(
            "remove_generated_skills_completed",
            {
                "remove_generated_skills_ms": remove_generated_skills_ms,
                "source": "removed" if generated_skills_removed else "already_clean",
            },
        )
    if on_provider_startup_event is not None:
        on_provider_startup_event("ensure_thread_started", {})
    ensure_thread_started_at = time.perf_counter()
    provider_thread_id = _ensure_provider_thread(runtime=runtime, session=session, launch_spec=launch_spec, on_provider_thread_id=on_provider_thread_id)
    ensure_provider_thread_ms = (time.perf_counter() - ensure_thread_started_at) * 1000
    if on_provider_startup_event is not None:
        on_provider_startup_event(
            "ensure_thread_completed",
            {
                "ensure_provider_thread_ms": ensure_provider_thread_ms,
                "provider_thread_id": provider_thread_id,
            },
        )
    if on_provider_startup_event is not None:
        on_provider_startup_event("event_sink_reset_started", {})
    event_sink_reset_started_at = time.perf_counter()
    with runtime.event_lock:
        runtime.current_event_sink = event_sink
        runtime.current_chunks = []
        runtime.streamed_agent_item_ids = set()
        runtime.pending_agent_json_chunks = {}
        runtime.emitted_structured_keys = set()
        runtime.current_error_text = None
        runtime.current_completion_received = False
        runtime.completion_queue = queue.Queue(maxsize=1)
    event_sink_reset_ms = (time.perf_counter() - event_sink_reset_started_at) * 1000
    if on_provider_startup_event is not None:
        on_provider_startup_event("event_sink_reset_completed", {"event_sink_reset_ms": event_sink_reset_ms})

    _debug_log(
        runtime,
        "Codex app-server debug: turn/start request sending",
        {
            "phase": "turn_start_request_sending",
            "provider_thread_id": provider_thread_id,
            "process_pid": runtime.process.pid,
            "process_returncode": runtime.process.poll(),
        },
    )
    if on_provider_startup_event is not None:
        on_provider_startup_event("turn_start_write_started", {"provider_thread_id": provider_thread_id})

    turn_start_sent_at: float | None = None

    def record_turn_start_sent(metadata: dict[str, object]) -> None:
        nonlocal turn_start_sent_at
        turn_start_sent_at = time.perf_counter()
        enriched_metadata = {
            **metadata,
            "provider_thread_id": provider_thread_id,
            "ensure_runtime_ms": ensure_runtime_ms,
            "ensure_provider_thread_ms": ensure_provider_thread_ms,
        }
        if on_provider_startup_event is not None:
            on_provider_startup_event("turn_start_write_sent", enriched_metadata)
        if on_provider_turn_start_sent is not None:
            on_provider_turn_start_sent(enriched_metadata)

    turn_start_request_started_at = time.perf_counter()
    turn_input = [
        {"type": "text", "text": input_text},
        *codex_skill_input_items(runtime.runtime_root, invoked_skills),
    ]
    turn = _send_request(
        runtime,
        "turn/start",
        {
            "threadId": provider_thread_id,
            "input": turn_input,
            "approvalPolicy": "never",
            "sandboxPolicy": _turn_sandbox_policy(launch_spec),
            "cwd": launch_spec.working_directory,
        },
        timeout=20.0,
        on_sent=record_turn_start_sent if on_provider_startup_event is not None or on_provider_turn_start_sent is not None else None,
    ).get("turn")
    turn_start_request_ack_ms = (
        time.perf_counter() - (turn_start_sent_at or turn_start_request_started_at)
    ) * 1000
    provider_turn_id = ""
    if isinstance(turn, dict):
        provider_turn_id = str(turn.get("id") or "").strip()
        if provider_turn_id:
            with runtime.active_turn_lock:
                runtime.current_provider_turn_id = provider_turn_id
    if on_provider_accepted is not None:
        on_provider_accepted(
            {
                "provider_thread_id": provider_thread_id,
                "provider_turn_id": provider_turn_id,
                "ensure_runtime_ms": ensure_runtime_ms,
                "ensure_provider_thread_ms": ensure_provider_thread_ms,
                "event_sink_reset_ms": event_sink_reset_ms,
                "remove_generated_skills_ms": remove_generated_skills_ms,
                "turn_start_request_ack_ms": turn_start_request_ack_ms,
            }
        )
    _debug_log(
        runtime,
        "Codex app-server debug: turn/start acknowledged",
        {
            "phase": "turn_start_acknowledged",
            "provider_thread_id": provider_thread_id,
            "provider_turn_id": provider_turn_id,
            "process_pid": runtime.process.pid,
            "process_returncode": runtime.process.poll(),
        },
    )

    wait_started_at = time.monotonic()
    deadline = wait_started_at + timeout_seconds if timeout_seconds is not None else None
    next_pending_log_at = wait_started_at + 30.0
    try:
        while True:
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                raise RuntimeError("Codex app-server turn timed out before completion.")
            wait_timeout = 1.0
            if deadline is not None:
                wait_timeout = max(0.01, min(wait_timeout, deadline - now))
            try:
                completion = runtime.completion_queue.get(timeout=wait_timeout)
                break
            except queue.Empty:
                with runtime.event_lock:
                    chunk_count = len(runtime.current_chunks)
                    pending_json_item_count = len(runtime.pending_agent_json_chunks)
                with runtime.active_turn_lock:
                    provider_turn_id = runtime.current_provider_turn_id
                process_returncode = runtime.process.poll()
                if process_returncode is not None:
                    raise RuntimeError(f"Codex app-server exited before turn completion with code {process_returncode}.")
                if time.monotonic() < next_pending_log_at:
                    continue
                next_pending_log_at += 30.0
                _debug_log(
                    runtime,
                    "Codex app-server debug: completion wait still pending",
                    {
                        "phase": "completion_wait_still_pending",
                        "elapsed_seconds": round(time.monotonic() - wait_started_at, 3),
                        "provider_thread_id": provider_thread_id,
                        "provider_turn_id": provider_turn_id,
                        "streamed_chunk_count": chunk_count,
                        "pending_agent_json_item_count": pending_json_item_count,
                        "process_pid": runtime.process.pid,
                        "process_returncode": process_returncode,
                    },
                )
    finally:
        with runtime.event_lock:
            runtime.current_event_sink = None
            chunks = list(runtime.current_chunks)
            error_text = runtime.current_error_text
            runtime.current_chunks = []
            runtime.streamed_agent_item_ids = set()
            runtime.pending_agent_json_chunks = {}
            runtime.emitted_structured_keys = set()
            runtime.current_error_text = None
            runtime.current_completion_received = False
        with runtime.active_turn_lock:
            if runtime.current_provider_turn_id == provider_turn_id:
                runtime.current_provider_turn_id = None

    status = str(completion.get("status") or "completed").strip().lower() if isinstance(completion, dict) else "completed"
    output = "".join(chunks).strip()
    fallback_output = error_text if status not in {"completed", "success", "succeeded"} and error_text else "(Codex completed without output.)"
    _debug_log(
        runtime,
        "Codex app-server debug: completion received",
        {
            "phase": "completion_received",
            "status": status,
            "elapsed_seconds": round(time.monotonic() - wait_started_at, 3),
            "provider_thread_id": provider_thread_id,
            "provider_turn_id": provider_turn_id,
            "streamed_chunk_count": len(chunks),
            "has_error_text": bool(error_text),
            "output_text_length": len(output),
            "process_pid": runtime.process.pid,
            "process_returncode": runtime.process.poll(),
        },
    )
    return CodexAppServerTurnResult(
        output_text=output or fallback_output,
        exit_code=0 if status in {"completed", "success", "succeeded"} else 1,
        provider_thread_id=provider_thread_id,
    )



def interrupt_codex_app_server_turn(session_id: str) -> bool:
    """Ask the live Codex app-server to interrupt the active turn."""
    with _RUNTIMES_LOCK:
        runtime = _RUNTIMES.get(session_id)
    if runtime is None or runtime.process.poll() is not None:
        return False
    with runtime.active_turn_lock:
        provider_thread_id = runtime.provider_thread_id
        provider_turn_id = runtime.current_provider_turn_id
    if not provider_thread_id or not provider_turn_id:
        return False
    try:
        _send_request(
            runtime,
            "turn/interrupt",
            {"threadId": provider_thread_id, "turnId": provider_turn_id},
            timeout=5.0,
        )
        return True
    except RuntimeError:
        return False



def close_codex_app_server_runtime(session_id: str) -> int:
    """Terminate and forget a live Codex app-server runtime."""
    with _RUNTIMES_LOCK:
        runtime = _RUNTIMES.pop(session_id, None)
    if runtime is None:
        return 0
    terminated = int(terminate_runtime_process(runtime.process))
    unregister_runtime_process(session_id, runtime.process)
    return terminated
