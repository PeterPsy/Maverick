"""Stateful Codex app-server protocol client."""

from __future__ import annotations

import json
from pathlib import Path
import queue
import subprocess
import threading
from typing import Any, Callable

from core.providers.models import RuntimeBackendLaunchSpec
from core.providers.codex_app_server_runtime_state import _CodexAppServerRuntime, _RUNTIMES, _RUNTIMES_LOCK
from core.providers.provider_codex import remove_codex_system_skills
from core.runtime.process_control import register_runtime_process, unregister_runtime_process
from core.runtime.runtime_session import RuntimeSessionRecord


def _ensure_runtime(
    *,
    session: RuntimeSessionRecord,
    launch_spec: RuntimeBackendLaunchSpec,
    command_runner,
) -> _CodexAppServerRuntime:
    with _RUNTIMES_LOCK:
        existing = _RUNTIMES.get(session.session_id)
        if existing is not None and existing.process.poll() is None:
            return existing
        if existing is not None:
            unregister_runtime_process(session.session_id, existing.process)
            _RUNTIMES.pop(session.session_id, None)

        process = command_runner(
            launch_spec.command,
            cwd=launch_spec.working_directory,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=launch_spec.env_overrides,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        runtime = _CodexAppServerRuntime(
            session_id=session.session_id,
            workspace_id=session.workspace_id,
            runtime_root=session.runtime_root,
            process=process,
        )
        runtime.reader_thread = threading.Thread(target=_reader_loop, args=(runtime,), daemon=True, name=f"codex-app-server-{session.session_id}")
        _RUNTIMES[session.session_id] = runtime
        register_runtime_process(session.session_id, process)
        runtime.reader_thread.start()

    _send_request(runtime, "initialize", {"clientInfo": {"name": "maverick", "version": "3.0.0"}}, timeout=10.0)
    return runtime



def _ensure_provider_thread(
    *,
    runtime: _CodexAppServerRuntime,
    session: RuntimeSessionRecord,
    launch_spec: RuntimeBackendLaunchSpec,
    on_provider_thread_id: Callable[[str], None] | None,
) -> str:
    with runtime.provider_thread_lock:
        if runtime.provider_thread_id:
            return runtime.provider_thread_id
        existing_thread_id = str(session.provider_thread_id or "").strip()
        params = _thread_params(session=session, launch_spec=launch_spec)
        if existing_thread_id:
            try:
                result = _send_request(runtime, "thread/resume", {"threadId": existing_thread_id, **params}, timeout=20.0)
            except RuntimeError:
                result = _send_request(runtime, "thread/start", params, timeout=20.0)
        else:
            result = _send_request(runtime, "thread/start", params, timeout=20.0)
        thread = result.get("thread") if isinstance(result.get("thread"), dict) else {}
        provider_thread_id = str(thread.get("id") or existing_thread_id).strip()
        if not provider_thread_id:
            raise RuntimeError("Codex app-server did not return a provider thread id.")
        runtime.provider_thread_id = provider_thread_id
        if on_provider_thread_id is not None and provider_thread_id != existing_thread_id:
            on_provider_thread_id(provider_thread_id)
        return provider_thread_id



def _thread_params(*, session: RuntimeSessionRecord, launch_spec: RuntimeBackendLaunchSpec) -> dict[str, Any]:
    return {
        "approvalPolicy": "never",
        "cwd": launch_spec.working_directory,
        "sandbox": "danger-full-access" if launch_spec.execution_mode == "full-access" else "read-only",
        "developerInstructions": session.system_prompt or "",
        "config": {"mcp_servers": {}},
    }



def _remove_generated_system_skills_if_needed(
    *,
    runtime: _CodexAppServerRuntime,
    launch_spec: RuntimeBackendLaunchSpec,
    session: RuntimeSessionRecord,
) -> bool:
    """Remove provider-generated system skills only when this runtime home needs cleanup."""
    raw_runtime_home = str(launch_spec.env_overrides.get("CODEX_HOME") or "").strip()
    runtime_home = raw_runtime_home or f"{session.runtime_root}/codex-home"
    system_root = Path(runtime_home) / "skills" / ".system"
    with runtime.generated_system_skills_lock:
        already_clean = runtime.generated_system_skills_cleaned_home == runtime_home
        if already_clean and not system_root.is_symlink() and not system_root.exists():
            return False
        remove_codex_system_skills(Path(runtime_home))
        runtime.generated_system_skills_cleaned_home = runtime_home
        return True



def _turn_sandbox_policy(launch_spec: RuntimeBackendLaunchSpec) -> dict[str, Any]:
    if launch_spec.execution_mode == "full-access":
        return {"type": "dangerFullAccess"}
    policy: dict[str, Any] = {
        "type": "workspaceWrite",
        "networkAccess": True,
        "excludeTmpdirEnvVar": False,
        "excludeSlashTmp": False,
    }
    writable_roots = [root for root in launch_spec.writable_roots if root and root != "/"]
    if writable_roots:
        policy["writableRoots"] = writable_roots
    return policy



def _send_request(
    runtime: _CodexAppServerRuntime,
    method: str,
    params: dict[str, Any],
    *,
    timeout: float,
    on_sent: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, Any]:
    with runtime.request_lock:
        request_id = runtime.next_request_id
        runtime.next_request_id += 1
        waiter: queue.Queue = queue.Queue(maxsize=1)
        runtime.response_waiters[request_id] = waiter
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    try:
        if runtime.process.stdin is None:
            raise RuntimeError("Codex app-server stdin is unavailable.")
        runtime.process.stdin.write(json.dumps(payload) + "\n")
        runtime.process.stdin.flush()
        if on_sent is not None:
            on_sent({"request_id": request_id})
    except Exception as error:
        with runtime.request_lock:
            runtime.response_waiters.pop(request_id, None)
        raise RuntimeError(f"Failed to send `{method}` to Codex app-server: {error}") from error

    try:
        response = waiter.get(timeout=timeout)
    except queue.Empty as error:
        with runtime.request_lock:
            runtime.response_waiters.pop(request_id, None)
        raise RuntimeError(f"`{method}` timed out against Codex app-server.") from error
    if isinstance(response, dict) and "error" in response:
        detail = response.get("error")
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
        raise RuntimeError(f"`{method}` failed against Codex app-server: {message}")
    result = response.get("result") if isinstance(response, dict) else None
    return result if isinstance(result, dict) else {}



def _reader_loop(runtime: _CodexAppServerRuntime) -> None:
    exit_reason = "stdout_closed"
    exit_error: str | None = None
    try:
        if runtime.process.stdout is None:
            exit_reason = "stdout_unavailable"
            return
        for line in runtime.process.stdout:
            payload = _decode_json_line(line)
            if payload is None:
                continue
            if "id" in payload and "method" not in payload:
                _resolve_response(runtime, payload)
                continue
            if "method" in payload and "id" in payload:
                _respond_to_server_request(runtime, payload)
                continue
            if "method" in payload:
                _handle_notification(runtime, payload)
    except Exception as error:
        exit_reason = "reader_exception"
        exit_error = f"{type(error).__name__}: {error}"
    finally:
        _handle_reader_loop_exit(runtime, reason=exit_reason, error=exit_error)
        with _RUNTIMES_LOCK:
            if _RUNTIMES.get(runtime.session_id) is runtime:
                _RUNTIMES.pop(runtime.session_id, None)
        unregister_runtime_process(runtime.session_id, runtime.process)


def _handle_reader_loop_exit(runtime: _CodexAppServerRuntime, *, reason: str, error: str | None) -> None:
    message = "Codex app-server stream ended before turn completion."
    with runtime.event_lock:
        had_active_turn = runtime.current_event_sink is not None
        completion_received = runtime.current_completion_received
        completion_pending = runtime.completion_queue.full()
        failed_before_completion = had_active_turn and not completion_received
        if failed_before_completion and not runtime.current_error_text:
            runtime.current_error_text = message if error is None else f"{message} {error}"
    _debug_log(
        runtime,
        "Codex app-server debug: reader loop exited",
        {
            "phase": "reader_loop_exited",
            "reason": reason,
            "error": error,
            "had_active_turn": had_active_turn,
            "completion_received": completion_received,
            "completion_pending": completion_pending,
            "provider_turn_id": runtime.current_provider_turn_id,
            "process_pid": runtime.process.pid,
            "process_returncode": runtime.process.poll(),
        },
    )
    if failed_before_completion:
        _put_completion(runtime, {"status": "failed"})



def _decode_json_line(line: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(str(line or "").strip())
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None



def _resolve_response(runtime: _CodexAppServerRuntime, payload: dict[str, Any]) -> None:
    request_id = payload.get("id")
    if not isinstance(request_id, int):
        return
    with runtime.request_lock:
        waiter = runtime.response_waiters.pop(request_id, None)
    if waiter is not None:
        waiter.put(payload)



def _respond_to_server_request(runtime: _CodexAppServerRuntime, payload: dict[str, Any]) -> None:
    method = str(payload.get("method") or "")
    if "approval" in method.lower():
        result: dict[str, Any] = {"action": "accept", "content": None}
    elif "input" in method.lower():
        result = {"answers": {}}
    else:
        result = {}
    response = {"jsonrpc": "2.0", "id": payload.get("id"), "result": result}
    try:
        if runtime.process.stdin is not None:
            runtime.process.stdin.write(json.dumps(response) + "\n")
            runtime.process.stdin.flush()
    except Exception:
        return
