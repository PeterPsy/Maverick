"""Apply generic runtime launch requests returned by app entrypoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from core.api.app_event_publication import declared_data_event_resources, publish_declared_app_events
from core.apps.dependencies import resolve_app_dependencies
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError
from core.apps.models import ParsedAppContract
from core.apps.runtime_event_hooks import dispatch_source_app_runtime_event
from core.apps.surfaces import resolve_workspace_app_surface
from core.providers.errors import ProviderError
from core.providers.service import resolve_provider_for_runtime_session
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.runtime_threads import create_runtime_thread
from core.runtime.service import create_runtime_session, record_runtime_event, transition_runtime_session, transition_runtime_turn
from core.runtime.turn_submission import interrupt_runtime_provider_turn, release_idle_runtime_processes, submit_runtime_turn_async
from core.shared.entrypoints import run_json_entrypoint


RUNTIME_REQUEST_KEYS = ("runtime_session_requests", "runtime_launch_requests")
RUNTIME_INTERRUPT_REQUEST_KEYS = ("runtime_turn_interrupt_requests", "runtime_interrupt_requests")


def apply_app_runtime_requests(
    state,
    *,
    result: dict[str, Any],
    workspace_id: str,
    app_id: str,
    source_root: Path,
    backend_entrypoint: str | None,
    data_root: str,
    parsed: ParsedAppContract,
    start_path: Path,
    actor_user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Create runtime sessions/turns requested by an app through a generic result envelope."""
    requests = _pop_runtime_requests(result)
    interrupt_requests = _pop_runtime_interrupt_requests(result)
    if not requests and not interrupt_requests:
        return []
    if requests and not parsed.contract.permissions.runtime.create_sessions:
        raise AppHostingError(f"App `{app_id}` requested runtime session creation without declaring runtime.create_sessions.")
    if not isinstance(requests, list):
        raise AppHostingError("App runtime launch requests must be a list.")
    results: list[dict[str, Any]] = []
    for request in requests:
        if not isinstance(request, dict):
            continue
        results.append(
            _apply_one_runtime_request(
                state,
                request=request,
                workspace_id=workspace_id,
                app_id=app_id,
                source_root=source_root,
                backend_entrypoint=backend_entrypoint,
                data_root=data_root,
                parsed=parsed,
                start_path=start_path,
                actor_user_id=actor_user_id,
            )
        )
    if not isinstance(interrupt_requests, list):
        raise AppHostingError("App runtime interrupt requests must be a list.")
    for request in interrupt_requests:
        if isinstance(request, dict):
            results.append(_apply_one_runtime_interrupt_request(state, request=request, workspace_id=workspace_id, app_id=app_id))
    _attach_runtime_request_results(result, results)
    return results


def _pop_runtime_requests(result: dict[str, Any]) -> object:
    response_json = result.get("json") if isinstance(result.get("json"), dict) else None
    for key in RUNTIME_REQUEST_KEYS:
        if key in result:
            return result.pop(key)
        if response_json is not None and key in response_json:
            return response_json.pop(key)
    return []


def _pop_runtime_interrupt_requests(result: dict[str, Any]) -> object:
    response_json = result.get("json") if isinstance(result.get("json"), dict) else None
    for key in RUNTIME_INTERRUPT_REQUEST_KEYS:
        if key in result:
            return result.pop(key)
        if response_json is not None and key in response_json:
            return response_json.pop(key)
    return []


def _attach_runtime_request_results(result: dict[str, Any], results: list[dict[str, Any]]) -> None:
    if not results:
        return
    response_json = result.get("json") if isinstance(result.get("json"), dict) else None
    if response_json is not None:
        response_json["runtime_request_results"] = results
        return
    result["runtime_request_results"] = results


def _apply_one_runtime_request(
    state,
    *,
    request: dict[str, Any],
    workspace_id: str,
    app_id: str,
    source_root: Path,
    backend_entrypoint: str | None,
    data_root: str,
    parsed: ParsedAppContract,
    start_path: Path,
    actor_user_id: str | None,
) -> dict[str, Any]:
    request_id = _text(request.get("request_id")) or str(uuid4())
    callback = request.get("callback") if isinstance(request.get("callback"), dict) else {}
    session = None
    turn = None
    callback_result: dict[str, Any] = {}
    status = "submitted"
    error = ""
    try:
        session = _runtime_session_for_request(
            state,
            request=request,
            workspace_id=workspace_id,
            app_id=app_id,
            parsed=parsed,
            start_path=start_path,
            actor_user_id=actor_user_id,
        )
        input_text = _long_text(request.get("input_text"))
        if not input_text:
            raise AppHostingError("Runtime launch request requires input_text.")
        turn, _events = submit_runtime_turn_async(
            state,
            session=session,
            input_text=input_text,
            client_message_id=_text(request.get("client_message_id")) or f"{app_id}:{request_id}",
            app_references=_list_of_dicts(request.get("app_references")),
            on_queued=lambda queued_turn, _events: callback_result.update(
                _invoke_runtime_request_callback(
                    state,
                    callback=callback,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    source_root=source_root,
                    backend_entrypoint=backend_entrypoint,
                    data_root=data_root,
                    parsed=parsed,
                    start_path=start_path,
                    request=request,
                    request_id=request_id,
                    status="submitted",
                    session_id=session.session_id if session is not None else "",
                    turn_id=queued_turn.turn_id,
                    error="",
                )
            ),
        )
    except Exception as exc:
        status = "failed"
        error = str(exc)
        _record_runtime_request_failed(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            request_id=request_id,
            session_id=session.session_id if session is not None else "",
            detail=error,
        )
        callback_result = _invoke_runtime_request_callback(
            state,
            callback=callback,
            workspace_id=workspace_id,
            app_id=app_id,
            source_root=source_root,
            backend_entrypoint=backend_entrypoint,
            data_root=data_root,
            parsed=parsed,
            start_path=start_path,
            request=request,
            request_id=request_id,
            status=status,
            session_id=session.session_id if session is not None else "",
            turn_id=turn.turn_id if turn is not None else "",
            error=error,
        )
    return {
        "request_id": request_id,
        "status": status,
        "runtime_session_id": session.session_id if session is not None else "",
        "turn_id": turn.turn_id if turn is not None else "",
        "error": error,
        "callback_status_code": int(callback_result.get("status_code", 0)) if isinstance(callback_result, dict) else 0,
    }


def _runtime_session_for_request(
    state,
    *,
    request: dict[str, Any],
    workspace_id: str,
    app_id: str,
    parsed: ParsedAppContract,
    start_path: Path,
    actor_user_id: str | None,
):
    existing_session_id = _text(request.get("runtime_session_id"))
    if existing_session_id:
        try:
            session = state.runtime_store.get_session(existing_session_id)
        except RuntimeSessionNotFoundError as exc:
            raise AppHostingError(f"Runtime session `{existing_session_id}` was not found.") from exc
        if session.workspace_id != workspace_id:
            raise AppHostingError(f"Runtime session `{existing_session_id}` is outside workspace `{workspace_id}`.")
        if session.source_app_id and session.source_app_id != app_id:
            raise AppHostingError(f"Runtime session `{existing_session_id}` is owned by another source app.")
        return session
    agent_id = _text(request.get("agent_id") or request.get("agent_type_id"))
    if not agent_id:
        raise AppHostingError("Runtime launch request requires agent_id.")
    system_prompt = _materialized_system_prompt(
        state,
        request=request,
        workspace_id=workspace_id,
        app_id=app_id,
        start_path=start_path,
    )
    session = create_runtime_session(
        state.runtime_store,
        session_id=str(uuid4()),
        workspace_id=workspace_id,
        agent_id=agent_id,
        requested_mode=request.get("requested_mode"),
        system_prompt=system_prompt,
        skill_ids=_list_of_text(request.get("skill_ids")),
        source_app_id=app_id,
        owner_user_id=actor_user_id,
        created_by_user_id=actor_user_id,
        grants=[],
        governance=state.workspace_store.get_governance(workspace_id),
        platform_allows_full_access=workspace_id == "default",
        start_path=start_path,
        observability_store=state.observability_store,
    )
    session = transition_runtime_session(
        state.runtime_store,
        session_id=session.session_id,
        target_status="running",
        observability_store=state.observability_store,
        start_path=start_path,
    )
    create_runtime_thread(
        state.runtime_store,
        workspace_id=workspace_id,
        thread_id=session.session_id,
        runtime_session_id=session.session_id,
        title=_text(request.get("title")) or _text(request.get("agent_label")) or agent_id,
        agent_label=_text(request.get("agent_label")) or agent_id,
        agent_type_id=_text(request.get("agent_type_id")) or agent_id,
        agent_role_id=_text(request.get("agent_role_id")),
        source_app_id=app_id,
        system_prompt=session.system_prompt or "",
        project_id=_text(request.get("project_id")) or None,
        now=session.started_at or session.updated_at,
    )
    return session


def _apply_one_runtime_interrupt_request(
    state,
    *,
    request: dict[str, Any],
    workspace_id: str,
    app_id: str,
) -> dict[str, Any]:
    turn_id = _text(request.get("turn_id"))
    if not turn_id:
        raise AppHostingError("Runtime interrupt request requires turn_id.")
    try:
        turn = state.runtime_store.get_turn(turn_id)
        session = state.runtime_store.get_session(turn.session_id)
    except Exception as exc:
        raise AppHostingError(f"Runtime turn `{turn_id}` was not found.") from exc
    if turn.workspace_id != workspace_id or session.workspace_id != workspace_id:
        raise AppHostingError(f"Runtime turn `{turn_id}` is outside workspace `{workspace_id}`.")
    if session.source_app_id and session.source_app_id != app_id:
        raise AppHostingError(f"Runtime turn `{turn_id}` is owned by another source app.")
    if turn.status not in {"queued", "active"}:
        return {"turn_id": turn_id, "status": turn.status, "interrupted": False}
    provider_id = _resolved_provider_id(state, session)
    provider_interrupted = interrupt_runtime_provider_turn(state, session)
    reason = _long_text(request.get("reason")) or "Interrupted by app request."
    updated = transition_runtime_turn(state.runtime_store, turn_id=turn_id, target_status="cancelled", failure_reason=reason)
    event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=updated.session_id,
        turn_id=updated.turn_id,
        plane="turn",
        event_type="runtime.turn.cancelled",
        payload={"reason": reason, "requested_by_app_id": app_id},
        event_bus=state.runtime_event_bus,
    )
    release_idle_runtime_processes(state, session_id=updated.session_id, provider_id=provider_id or "unconfigured", reason="app_turn_interrupted")
    dispatch_source_app_runtime_event(
        state,
        session=session,
        turn=updated,
        event_type="runtime.turn.failed",
        failure_reason=reason,
    )
    return {
        "turn_id": updated.turn_id,
        "status": updated.status,
        "interrupted": True,
        "provider_interrupted": provider_interrupted,
        "event_id": event.event_id,
    }


def _resolved_provider_id(state, session) -> str | None:
    if session.provider_id:
        return session.provider_id
    try:
        provider, _selection = resolve_provider_for_runtime_session(state.provider_store, session=session)
    except ProviderError:
        return None
    return provider.provider_id


def _materialized_system_prompt(
    state,
    *,
    request: dict[str, Any],
    workspace_id: str,
    app_id: str,
    start_path: Path,
) -> str:
    direct = _long_text(request.get("system_prompt"))
    if direct:
        return direct
    prompt_request = request.get("system_prompt_request")
    if not isinstance(prompt_request, dict):
        return ""
    provider_result = _invoke_dependency_backend(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        dependency_alias=_text(prompt_request.get("dependency_alias")),
        body=prompt_request.get("body") if isinstance(prompt_request.get("body"), dict) else {},
        start_path=start_path,
    )
    response_path = _list_of_text(prompt_request.get("response_path")) or ["rendered"]
    value = _value_at_path(provider_result.get("json") if isinstance(provider_result.get("json"), dict) else provider_result, response_path)
    return _long_text(value)


def _invoke_dependency_backend(
    state,
    *,
    workspace_id: str,
    app_id: str,
    dependency_alias: str,
    body: dict[str, Any],
    start_path: Path,
) -> dict[str, Any]:
    if not dependency_alias:
        raise AppHostingError("Dependency backend request requires dependency_alias.")
    dependencies = resolve_app_dependencies(
        state.app_store,
        workspace_id=workspace_id,
        consumer_app_id=app_id,
        workspace_store=state.workspace_store,
        start_path=start_path,
    )
    dependency = next((item for item in dependencies.get("dependencies", []) if item.get("alias") == dependency_alias), None)
    provider_ids = dependency.get("selected_provider_app_ids") if isinstance(dependency, dict) else []
    provider_id = str(provider_ids[0]).strip() if isinstance(provider_ids, list) and provider_ids else ""
    if not provider_id:
        raise AppHostingError(f"Dependency alias `{dependency_alias}` has no selected provider app.")
    try:
        binding = state.app_store.get_workspace_app_binding(workspace_id=workspace_id, app_id=provider_id)
        provider_source_root, provider_parsed = resolve_workspace_app_surface(state.app_store, binding=binding, start_path=start_path)
    except WorkspaceAppBindingNotFoundError as exc:
        raise AppHostingError(f"Dependency provider `{provider_id}` is not enabled.") from exc
    backend = provider_parsed.contract.entrypoints.backend
    if backend is None:
        raise AppHostingError(f"Dependency provider `{provider_id}` does not expose a backend.")
    result = run_json_entrypoint(
        provider_source_root / backend,
        payload={
            "surface": "dependency_backend",
            "workspace_id": workspace_id,
            "app_id": provider_id,
            "data_root": binding.data_root,
            "body": body,
            "runtime_session_id": "",
            "turn_id": "",
        },
        cwd=provider_source_root,
        timeout_seconds=30,
    )
    status_code = int(result.get("status_code", 200))
    if status_code >= 400:
        raise AppHostingError(str(result.get("json") or result))
    return result


def _invoke_runtime_request_callback(
    state,
    *,
    callback: dict[str, Any],
    workspace_id: str,
    app_id: str,
    source_root: Path,
    backend_entrypoint: str | None,
    data_root: str,
    parsed: ParsedAppContract,
    start_path: Path,
    request: dict[str, Any],
    request_id: str,
    status: str,
    session_id: str,
    turn_id: str,
    error: str,
) -> dict[str, Any]:
    action = _text(callback.get("action"))
    if not action or backend_entrypoint is None:
        return {}
    payload = callback.get("payload") if isinstance(callback.get("payload"), dict) else {}
    result = run_json_entrypoint(
        source_root / backend_entrypoint,
        payload={
            "surface": "runtime_request_callback",
            "workspace_id": workspace_id,
            "app_id": app_id,
            "data_root": data_root,
            "body": {
                **payload,
                "action": action,
                "request_id": request_id,
                "runtime_request_status": status,
                "runtime_session_id": session_id,
                "turn_id": turn_id,
                "error": error,
                "request": request,
            },
            "runtime_session_id": session_id,
            "turn_id": turn_id,
        },
        cwd=source_root,
        timeout_seconds=30,
    )
    publish_declared_app_events(
        state.app_event_bus,
        result,
        workspace_id=workspace_id,
        app_id=app_id,
        declared_resources=declared_data_event_resources(parsed.contract.capabilities.data_events),
        remove_from_result=True,
    )
    status_code = int(result.get("status_code", 200))
    if status_code >= 400:
        raise AppHostingError(str(result.get("json") or result))
    return result


def _record_runtime_request_failed(
    state,
    *,
    workspace_id: str,
    app_id: str,
    request_id: str,
    session_id: str,
    detail: str,
) -> None:
    if not session_id:
        return
    record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        plane="runtime",
        event_type="runtime.app_request.failed",
        payload={"workspace_id": workspace_id, "app_id": app_id, "request_id": request_id, "detail": detail},
        event_bus=state.runtime_event_bus,
    )


def _value_at_path(payload: object, path: list[str]) -> object:
    current = payload
    for part in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(part)
    return current


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _list_of_text(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _long_text(value: object) -> str:
    return str(value or "").strip()
