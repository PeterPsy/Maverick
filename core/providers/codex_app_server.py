"""Stateful Codex app-server protocol client."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import queue
import subprocess
import threading
from typing import Any, Callable

from core.providers.models import RuntimeBackendLaunchSpec
from core.providers.provider_codex import remove_codex_system_skills
from core.runtime.execution_events import RuntimeExecutionEvent, RuntimeExecutionEventSink, parse_provider_json_event
from core.runtime.process_control import register_runtime_process, unregister_runtime_process
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
        runtime.current_error_text = None
        runtime.completion_queue = queue.Queue(maxsize=1)

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

    try:
        completion = runtime.completion_queue.get()
    finally:
        with runtime.event_lock:
            runtime.current_event_sink = None
            chunks = list(runtime.current_chunks)
            error_text = runtime.current_error_text
            runtime.current_chunks = []
            runtime.streamed_agent_item_ids = set()
            runtime.current_error_text = None

    status = str(completion.get("status") or "completed").strip().lower() if isinstance(completion, dict) else "completed"
    output = "".join(chunks).strip()
    fallback_output = error_text if status not in {"completed", "success", "succeeded"} and error_text else "(Codex completed without output.)"
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
        runtime = _CodexAppServerRuntime(session_id=session.session_id, process=process)
        runtime.reader_thread = threading.Thread(target=_reader_loop, args=(runtime,), daemon=True, name=f"codex-app-server-{session.session_id}")
        _RUNTIMES[session.session_id] = runtime
        register_runtime_process(session.session_id, process)
        runtime.reader_thread.start()

    _send_request(runtime, "initialize", {"clientInfo": {"name": "maverick-v3", "version": "3.0.0"}}, timeout=10.0)
    _remove_generated_system_skills(launch_spec=launch_spec, session=session)
    return runtime


def _ensure_provider_thread(
    *,
    runtime: _CodexAppServerRuntime,
    session: RuntimeSessionRecord,
    launch_spec: RuntimeBackendLaunchSpec,
    on_provider_thread_id: Callable[[str], None] | None,
) -> str:
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
        "sandbox": "danger-full-access" if launch_spec.execution_mode == "full-access" else "workspace-write",
        "developerInstructions": session.system_prompt or "",
        "config": {"mcp_servers": {}},
    }


def _remove_generated_system_skills(*, launch_spec: RuntimeBackendLaunchSpec, session: RuntimeSessionRecord) -> None:
    raw_runtime_home = str(launch_spec.env_overrides.get("CODEX_HOME") or "").strip()
    runtime_home = raw_runtime_home or f"{session.runtime_root}/codex-home"
    remove_codex_system_skills(Path(runtime_home))


def _turn_sandbox_policy(launch_spec: RuntimeBackendLaunchSpec) -> dict[str, Any]:
    if launch_spec.execution_mode == "full-access":
        return {"type": "dangerFullAccess"}
    policy: dict[str, Any] = {"type": "workspaceWrite", "networkAccess": True}
    readable_roots = [root for root in launch_spec.readable_roots if root and root != "/"]
    if readable_roots:
        policy["readOnlyAccess"] = {"type": "restricted", "includePlatformDefaults": True, "readableRoots": readable_roots}
    writable_roots = [root for root in launch_spec.writable_roots if root and root != "/"]
    if writable_roots:
        policy["writableRoots"] = writable_roots
    return policy


def _send_request(runtime: _CodexAppServerRuntime, method: str, params: dict[str, Any], *, timeout: float) -> dict[str, Any]:
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
    try:
        if runtime.process.stdout is None:
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
    finally:
        with _RUNTIMES_LOCK:
            if _RUNTIMES.get(runtime.session_id) is runtime:
                _RUNTIMES.pop(runtime.session_id, None)
        unregister_runtime_process(runtime.session_id, runtime.process)


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


def _handle_notification(runtime: _CodexAppServerRuntime, payload: dict[str, Any]) -> None:
    method = str(payload.get("method") or "")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    if method == "turn/started":
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        provider_turn_id = str(turn.get("id") or "").strip()
        if provider_turn_id:
            runtime.current_provider_turn_id = provider_turn_id
        return
    if method == "turn/completed":
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        _put_completion(runtime, {"status": str(turn.get("status") or "completed")})
        return
    if method == "item/agentMessage/delta":
        delta = str(params.get("delta") or "")
        if delta:
            item_id = _item_id(params)
            with runtime.event_lock:
                runtime.current_chunks.append(delta)
                if item_id:
                    runtime.streamed_agent_item_ids.add(item_id)
            _emit(runtime, RuntimeExecutionEvent(event_type="runtime.output.delta", payload={"text": delta, "provider_event_type": method}))
        return
    if method in {"item/started", "item/completed"}:
        item = params.get("item") if isinstance(params.get("item"), dict) else {}
        _handle_item_event(runtime, provider_type=method.replace("/", "."), item=item)
        return
    if method == "error":
        error_text = _extract_error_text(params)
        with runtime.event_lock:
            runtime.current_error_text = error_text
        _emit(runtime, RuntimeExecutionEvent(event_type="runtime.step.updated", payload={"label": "Codex app-server error", "raw": params}))
        if not bool(params.get("willRetry")):
            _put_completion(runtime, {"status": "failed"})
        return
    _handle_generic_notification(runtime, method=method, params=params)


def _extract_error_text(params: dict[str, Any]) -> str:
    error = params.get("error") if isinstance(params.get("error"), dict) else {}
    details = str(error.get("additionalDetails") or "").strip()
    message = str(error.get("message") or "").strip()
    if details:
        return details
    if message:
        return message
    return "Codex app-server failed."


def _handle_item_event(runtime: _CodexAppServerRuntime, *, provider_type: str, item: dict[str, Any]) -> None:
    if _is_agent_message_item(item) and provider_type.endswith("completed"):
        text = str(item.get("text") or "").strip()
        if text:
            item_id = _item_id(item)
            with runtime.event_lock:
                already_streamed = item_id in runtime.streamed_agent_item_ids if item_id else bool(runtime.current_chunks)
                if not already_streamed:
                    runtime.current_chunks.append(text)
            if not already_streamed:
                _emit(runtime, RuntimeExecutionEvent(event_type="runtime.output.delta", payload={"text": text, "provider_event_type": provider_type}))
            return
    event = parse_provider_json_event(json.dumps({"type": provider_type, "item": item}))
    if event is not None:
        _emit(runtime, event)
    structured = _structured_content_from_completed_item(provider_type=provider_type, item=item)
    if structured is not None:
        _emit(
            runtime,
            RuntimeExecutionEvent(
                event_type="runtime.output.structured",
                payload={
                    "structured_content": structured,
                    "provider_event_type": provider_type,
                    "tool_call_id": _item_id(item) or None,
                },
            ),
        )


def _is_agent_message_item(item: dict[str, Any]) -> bool:
    return str(item.get("type") or "").strip() in {"agentMessage", "agent_message"}


def _structured_content_from_completed_item(*, provider_type: str, item: dict[str, Any]) -> dict[str, Any] | None:
    if not provider_type.endswith("completed"):
        return None
    if str(item.get("type") or "").strip() != "commandExecution":
        return None
    output = str(item.get("aggregatedOutput") or item.get("aggregated_output") or item.get("stdout") or "").strip()
    if not output:
        return None
    payload = _decode_json_object(output)
    if payload is None:
        return None
    chat_render = payload.get("chat_render")
    if not isinstance(chat_render, dict):
        return None
    kind = str(chat_render.get("kind") or "").strip()
    if not kind:
        return None
    content_payload = chat_render.get("payload") if isinstance(chat_render.get("payload"), dict) else chat_render
    return {"kind": kind, "payload": content_payload}


def _decode_json_object(value: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(value[start : end + 1])
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _item_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("itemId") or item.get("item_id") or "").strip()


def _handle_generic_notification(runtime: _CodexAppServerRuntime, *, method: str, params: dict[str, Any]) -> None:
    provider_type = method.replace("/", ".")
    event = parse_provider_json_event(json.dumps({"type": provider_type, "item": params}))
    if event is not None:
        _emit(runtime, event)
        return
    _emit(runtime, RuntimeExecutionEvent(event_type="runtime.step.updated", payload={"label": provider_type.replace(".", " "), "provider_event_type": method, "raw": params}))


def _put_completion(runtime: _CodexAppServerRuntime, value: dict[str, Any]) -> None:
    try:
        runtime.completion_queue.put_nowait(value)
    except queue.Full:
        return


def _emit(runtime: _CodexAppServerRuntime, event: RuntimeExecutionEvent) -> None:
    with runtime.event_lock:
        sink = runtime.current_event_sink
    if sink is not None:
        sink(event)
