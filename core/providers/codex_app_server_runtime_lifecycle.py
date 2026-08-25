"""Lifecycle controls for persistent Codex app-server runtimes."""

from __future__ import annotations

from core.providers.codex_app_server_runtime_state import _RUNTIMES, _RUNTIMES_LOCK
from core.providers.codex_app_server_runtime_transport import _send_request
from core.runtime.process_control import (
    terminate_runtime_process,
    unregister_runtime_process,
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
