"""Lifecycle controls for persistent Codex app-server runtimes."""

from __future__ import annotations

import subprocess
from core.providers.models import RuntimeBackendLaunchSpec
from core.runtime.runtime_session import RuntimeSessionRecord

from core.providers.codex_app_server_runtime_state import _RUNTIMES, _RUNTIMES_LOCK
from core.providers.codex_app_server_runtime_transport import _send_request
from core.runtime.process_control import (
    terminate_runtime_process,
    unregister_runtime_process,
)


def interrupt_codex_app_server_turn(session_id: str) -> bool:
    """Ask the live Codex app-server to interrupt the active turn."""
    from core.device_use.computer_actor_registry import cancel_computer_actor
    cancel_computer_actor(session_id)
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
    from core.device_use.computer_actor_registry import cancel_computer_actor
    cancel_computer_actor(session_id, close=True)
    with _RUNTIMES_LOCK:
        runtime = _RUNTIMES.pop(session_id, None)
    if runtime is None:
        return 0
    terminated = int(terminate_runtime_process(runtime.process))
    unregister_runtime_process(session_id, runtime.process)
    return terminated


def prewarm_codex_app_server_runtime(
    *,
    session: RuntimeSessionRecord,
    launch_spec: RuntimeBackendLaunchSpec,
    command_runner=subprocess.Popen,
) -> str:
    """Start the Codex app-server and bind a provider thread before the next turn."""
    runtime = _ensure_runtime(session=session, launch_spec=launch_spec, command_runner=command_runner)
    _remove_generated_system_skills_if_needed(runtime=runtime, launch_spec=launch_spec, session=session)
    return _ensure_provider_thread(runtime=runtime, session=session, launch_spec=launch_spec)
