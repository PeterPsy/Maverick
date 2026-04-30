"""Stateful Codex app-server protocol client."""

from __future__ import annotations

from dataclasses import dataclass, field
import queue
import subprocess
import threading
import time
from typing import Callable

from core.providers.models import RuntimeBackendLaunchSpec
from core.runtime.execution_events import RuntimeExecutionEventSink
from core.runtime.process_control import unregister_runtime_process
from core.runtime.runtime_session import RuntimeSessionRecord


@dataclass
class CodexAppServerTurnResult:
    """Result of one Codex app-server turn."""

    output_text: str
    exit_code: int
    provider_thread_id: str



@dataclass
class _CodexAppServerRuntime:
    """Live app-server process and request state for one runtime session."""

    session_id: str
    workspace_id: str
    runtime_root: str
    process: subprocess.Popen
    request_lock: threading.Lock = field(default_factory=threading.Lock)
    event_lock: threading.Lock = field(default_factory=threading.Lock)
    response_waiters: dict[int, queue.Queue] = field(default_factory=dict)
    next_request_id: int = 1
    provider_thread_id: str | None = None
    current_provider_turn_id: str | None = None
    current_event_sink: RuntimeExecutionEventSink | None = None
    current_chunks: list[str] = field(default_factory=list)
    streamed_agent_item_ids: set[str] = field(default_factory=set)
    pending_agent_json_chunks: dict[str, list[str]] = field(default_factory=dict)
    emitted_structured_keys: set[str] = field(default_factory=set)
    current_error_text: str | None = None
    completion_queue: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=1))
    reader_thread: threading.Thread | None = None


_RUNTIMES: dict[str, _CodexAppServerRuntime] = {}
_RUNTIMES_LOCK = threading.Lock()



def execute_codex_app_server_turn(
    *,
    session: RuntimeSessionRecord,
    launch_spec: RuntimeBackendLaunchSpec,
    input_text: str,
    event_sink: RuntimeExecutionEventSink | None,
    timeout_seconds: int | None,
    on_provider_thread_id: Callable[[str], None] | None = None,
    command_runner=subprocess.Popen,
) -> CodexAppServerTurnResult:
    """Execute one turn against a persistent Codex app-server thread."""
    runtime = _ensure_runtime(session=session, launch_spec=launch_spec, command_runner=command_runner)
    _remove_generated_system_skills(launch_spec=launch_spec, session=session)
    provider_thread_id = _ensure_provider_thread(runtime=runtime, session=session, launch_spec=launch_spec, on_provider_thread_id=on_provider_thread_id)
    with runtime.event_lock:
        runtime.current_event_sink = event_sink
        runtime.current_chunks = []
        runtime.streamed_agent_item_ids = set()
        runtime.pending_agent_json_chunks = {}
        runtime.emitted_structured_keys = set()
        runtime.current_error_text = None
        runtime.completion_queue = queue.Queue(maxsize=1)

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
    turn = _send_request(
        runtime,
        "turn/start",
        {
            "threadId": provider_thread_id,
            "input": [{"type": "text", "text": input_text}],
            "approvalPolicy": "never",
            "sandboxPolicy": _turn_sandbox_policy(launch_spec),
            "cwd": launch_spec.working_directory,
        },
        timeout=20.0,
    ).get("turn")
    if isinstance(turn, dict):
        provider_turn_id = str(turn.get("id") or "").strip()
        if provider_turn_id:
            runtime.current_provider_turn_id = provider_turn_id
    _debug_log(
        runtime,
        "Codex app-server debug: turn/start acknowledged",
        {
            "phase": "turn_start_acknowledged",
            "provider_thread_id": provider_thread_id,
            "provider_turn_id": runtime.current_provider_turn_id,
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
            "provider_turn_id": runtime.current_provider_turn_id,
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
    if not runtime.provider_thread_id or not runtime.current_provider_turn_id:
        return False
    try:
        _send_request(
            runtime,
            "turn/interrupt",
            {"threadId": runtime.provider_thread_id, "turnId": runtime.current_provider_turn_id},
            timeout=5.0,
        )
        return True
    except RuntimeError:
        return False



def close_codex_app_server_runtime(session_id: str) -> None:
    """Forget a live Codex app-server runtime after process termination."""
    with _RUNTIMES_LOCK:
        runtime = _RUNTIMES.pop(session_id, None)
    if runtime is not None:
        unregister_runtime_process(session_id, runtime.process)
