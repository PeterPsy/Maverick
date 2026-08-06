"""Apply generic runtime launch requests returned by app entrypoints."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
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
from core.runtime.app_streams import RuntimeAppStreamError, RuntimeAppStreamRecord
from core.runtime.runtime_session import runtime_session_allows_user_thread
from core.runtime.runtime_threads import create_runtime_thread
from core.runtime.service import (
    create_runtime_session,
    record_runtime_event,
    request_runtime_turn_cancellation,
    transition_runtime_session,
    transition_runtime_turn,
)
from core.runtime.thread_catalog_events import set_thread_availability
from core.runtime.turn_submission import interrupt_runtime_provider_turn, release_idle_runtime_processes, submit_runtime_turn_async
from core.secrets.app_delivery import AppSecretRequest, resolve_app_secret_payload_requests
from core.secrets.errors import SecretError
from core.skills.runtime_catalog import runtime_skill_catalog_app_id_for_request
from core.shared.entrypoints import run_json_entrypoint
from core.workspaces.paths import workspace_paths


RUNTIME_REQUEST_KEYS = ("runtime_session_requests", "runtime_launch_requests")
RUNTIME_INTERRUPT_REQUEST_KEYS = ("runtime_turn_interrupt_requests", "runtime_interrupt_requests")
DEPENDENCY_BACKEND_REQUEST_KEYS = ("dependency_backend_requests",)
MAX_RUNTIME_REQUEST_ATTACHMENTS = 5
ATTACHMENT_STORAGE_PREFIXES = (("storage", "uploaded"), ("storage", "generated"))


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
    """Apply platform-owned requests returned by an app through a generic result envelope."""
    requests = _pop_runtime_requests(result)
    interrupt_requests = _pop_runtime_interrupt_requests(result)
    dependency_backend_requests = _pop_dependency_backend_requests(result)
    if not requests and not interrupt_requests and not dependency_backend_requests:
        return []
    if requests and not parsed.contract.permissions.runtime.create_sessions:
        raise AppHostingError(f"App `{app_id}` requested runtime session creation without declaring runtime.create_sessions.")
    if interrupt_requests and not parsed.contract.permissions.runtime.create_sessions:
        raise AppHostingError(f"App `{app_id}` requested runtime interrupt without declaring runtime.create_sessions.")
    if not isinstance(requests, list):
        raise AppHostingError("App runtime launch requests must be a list.")
    if not isinstance(dependency_backend_requests, list):
        raise AppHostingError("App dependency backend requests must be a list.")
    dependency_results: list[dict[str, Any]] = []
    for request in dependency_backend_requests:
        if isinstance(request, dict):
            dependency_results.append(
                _apply_one_dependency_backend_request(
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
    _attach_dependency_backend_request_results(result, dependency_results)
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
    visible_results: list[dict[str, Any]] = []
    for request_result in results:
        visible = bool(request_result.pop("_visible", True))
        if visible:
            visible_results.append(request_result)
    _attach_runtime_request_results(result, visible_results)
    return results


def invoke_dependency_backend_request(
    state,
    *,
    workspace_id: str,
    app_id: str,
    dependency_alias: str,
    body: dict[str, Any],
    start_path: Path,
    provider_app_id: str | None = None,
    user=None,
) -> dict[str, Any]:
    """Invoke one selected dependency backend through the same platform boundary used by apps."""
    return _invoke_dependency_backend(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        dependency_alias=dependency_alias,
        body=body,
        start_path=start_path,
        provider_app_id=provider_app_id,
        user=user,
    )


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


def _pop_dependency_backend_requests(result: dict[str, Any]) -> object:
    response_json = result.get("json") if isinstance(result.get("json"), dict) else None
    for key in DEPENDENCY_BACKEND_REQUEST_KEYS:
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


def _attach_dependency_backend_request_results(result: dict[str, Any], results: list[dict[str, Any]]) -> None:
    if not results:
        return
    response_json = result.get("json") if isinstance(result.get("json"), dict) else None
    if response_json is not None:
        response_json["dependency_backend_request_results"] = results
        return
    result["dependency_backend_request_results"] = results


def _apply_one_dependency_backend_request(
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
    dependency_alias = _text(request.get("dependency_alias") or request.get("alias"))
    body = request.get("body") if isinstance(request.get("body"), dict) else {}
    callback = request.get("callback") if isinstance(request.get("callback"), dict) else {}
    try:
        result = _invoke_dependency_backend(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            dependency_alias=dependency_alias,
            body=body,
            start_path=start_path,
        )
        callback_result = _safe_dependency_backend_request_callback(
            state,
            callback=callback,
            workspace_id=workspace_id,
            app_id=app_id,
            source_root=source_root,
            backend_entrypoint=backend_entrypoint,
            data_root=data_root,
            parsed=parsed,
            request=request,
            request_id=request_id,
            dependency_alias=dependency_alias,
            status="completed",
            provider_result=result,
            error="",
            start_path=start_path,
            actor_user_id=actor_user_id,
        )
    except Exception as exc:
        callback_result = _safe_dependency_backend_request_callback(
            state,
            callback=callback,
            workspace_id=workspace_id,
            app_id=app_id,
            source_root=source_root,
            backend_entrypoint=backend_entrypoint,
            data_root=data_root,
            parsed=parsed,
            request=request,
            request_id=request_id,
            dependency_alias=dependency_alias,
            status="failed",
            provider_result={},
            error=str(exc),
            start_path=start_path,
            actor_user_id=actor_user_id,
        )
        return {
            "request_id": request_id,
            "dependency_alias": dependency_alias,
            "status": "failed",
            "status_code": 500,
            "error": str(exc),
            "callback_status_code": int(callback_result.get("status_code", 0)) if isinstance(callback_result, dict) else 0,
        }
    return {
        "request_id": request_id,
        "dependency_alias": dependency_alias,
        "provider_app_id": _text(result.get("dependency_provider_app_id")),
        "status": "completed",
        "status_code": int(result.get("status_code", 200)),
        "callback_status_code": int(callback_result.get("status_code", 0)) if isinstance(callback_result, dict) else 0,
    }


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
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    request_id = _text(request.get("request_id")) or str(uuid4())
    callback = request.get("callback") if isinstance(request.get("callback"), dict) else {}
    session = None
    turn = None
    callback_result: dict[str, Any] = {}
    status = "submitted"
    error = ""
    stream = None
    stream_requested = bool(request.get("create_stream"))
    actor_id = _text(actor_user_id) or "system"
    try:
        if stream_requested:
            idempotency_key = _text(request.get("idempotency_key"))
            if not idempotency_key:
                raise AppHostingError("Streamed runtime launch request requires idempotency_key.")
            if len(idempotency_key) > 256:
                raise AppHostingError("Runtime launch request idempotency_key is too long.")
            timestamp = datetime.now(tz=UTC)
            stream, inserted = state.runtime_store.reserve_app_stream(
                RuntimeAppStreamRecord(
                    stream_id=str(uuid4()),
                    workspace_id=workspace_id,
                    source_app_id=app_id,
                    actor_id=actor_id,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=_runtime_request_fingerprint(request),
                    session_id="",
                    turn_id="",
                    status="reserving",
                    last_sequence=0,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
            if not inserted:
                return {
                    "request_id": request_id,
                    "status": stream.status,
                    "stream_id": stream.stream_id,
                    "runtime_session_id": stream.session_id,
                    "turn_id": stream.turn_id,
                    "error": "",
                    "callback_status_code": 0,
                    "idempotent_replay": True,
                    "_visible": request.get("result_visibility") != "internal",
                }
        attachments = _validated_runtime_request_attachments(
            request.get("attachments"),
            workspace_id=workspace_id,
            start_path=start_path,
        )
        session = _runtime_session_for_request(
            state,
            request=request,
            workspace_id=workspace_id,
            app_id=app_id,
            parsed=parsed,
            start_path=start_path,
            actor_user_id=actor_user_id,
        )
        session = _apply_project_root_capability(
            state,
            session=session,
            request=request,
            workspace_id=workspace_id,
            app_id=app_id,
            actor_id=actor_id,
            data_root=data_root,
            start_path=start_path,
        )
        input_text = _long_text(request.get("input_text"))
        if not input_text:
            raise AppHostingError("Runtime launch request requires input_text.")
        def on_queued(queued_turn, _events) -> None:
            nonlocal stream
            if stream is not None:
                stream = state.runtime_store.bind_app_stream(
                    stream_id=stream.stream_id,
                    workspace_id=workspace_id,
                    source_app_id=app_id,
                    session_id=session.session_id,
                    turn_id=queued_turn.turn_id,
                )
            callback_result.update(
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
                    session_id=session.session_id,
                    turn_id=queued_turn.turn_id,
                    stream_id=stream.stream_id if stream is not None else "",
                    actor_id=actor_id,
                    error="",
                )
            )

        turn, _events = submit_runtime_turn_async(
            state,
            session=session,
            input_text=input_text,
            client_message_id=_text(request.get("client_message_id")) or f"{app_id}:{request_id}",
            attachments=attachments,
            app_references=_list_of_dicts(request.get("app_references")),
            on_queued=on_queued,
        )
    except Exception as exc:
        status = "failed"
        error = str(exc)
        if stream is not None:
            try:
                stream = state.runtime_store.fail_app_stream(
                    stream_id=stream.stream_id,
                    workspace_id=workspace_id,
                    source_app_id=app_id,
                )
            except RuntimeAppStreamError:
                pass
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
            stream_id=stream.stream_id if stream is not None else "",
            actor_id=actor_id,
            error=error,
        )
    return {
        "request_id": request_id,
        "status": status,
        "runtime_session_id": session.session_id if session is not None else "",
        "turn_id": turn.turn_id if turn is not None else "",
        "stream_id": stream.stream_id if stream is not None else "",
        "error": error,
        "callback_status_code": int(callback_result.get("status_code", 0)) if isinstance(callback_result, dict) else 0,
        "_visible": request.get("result_visibility") != "internal",
    }


def _runtime_session_for_request(
    state,
    *,
    request: dict[str, Any],
    workspace_id: str,
    app_id: str,
    parsed: ParsedAppContract,
    start_path: Path,
    actor_user_id: str | None = None,
):
    existing_session_id = _text(request.get("runtime_session_id"))
    if existing_session_id:
        try:
            session = state.runtime_store.get_session(existing_session_id)
        except RuntimeSessionNotFoundError as exc:
            raise AppHostingError(f"Runtime session `{existing_session_id}` was not found.") from exc
        if session.workspace_id != workspace_id:
            raise AppHostingError(f"Runtime session `{existing_session_id}` is outside workspace `{workspace_id}`.")
        if not runtime_session_allows_user_thread(session):
            raise AppHostingError(f"Runtime session `{existing_session_id}` is hidden and must be operated through inter-agent APIs.")
        if session.source_app_id != app_id:
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
        skill_catalog_app_id=runtime_skill_catalog_app_id_for_request(
            state.app_store,
            workspace_id=workspace_id,
            source_app_id=app_id,
            workspace_store=state.workspace_store,
            start_path=start_path,
        ),
        source_app_id=app_id,
        owner_user_id=_text(actor_user_id) or None,
        created_by_user_id=_text(actor_user_id) or None,
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


def _validated_runtime_request_attachments(
    value: object,
    *,
    workspace_id: str,
    start_path: Path,
) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AppHostingError("Runtime launch request attachments must be a list.")
    if len(value) > MAX_RUNTIME_REQUEST_ATTACHMENTS:
        raise AppHostingError(f"Runtime launch request attachments must contain at most {MAX_RUNTIME_REQUEST_ATTACHMENTS} items.")
    paths = workspace_paths(workspace_id, start_path=start_path)
    attachments: list[dict[str, object]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise AppHostingError(f"Runtime launch request attachment #{index + 1} must be an object.")
        relative_path = _validated_attachment_storage_path(item)
        candidate = (paths.root / PurePosixPath(relative_path)).resolve()
        _require_attachment_inside_storage(candidate, paths=paths, relative_path=relative_path)
        if not candidate.is_file():
            raise AppHostingError(f"Runtime launch request attachment `{relative_path}` was not found in workspace storage.")
        attachments.append(_runtime_attachment_payload(item, relative_path=relative_path))
    return attachments


def _apply_project_root_capability(
    state,
    *,
    session,
    request: dict[str, Any],
    workspace_id: str,
    app_id: str,
    actor_id: str,
    data_root: str,
    start_path: Path,
):
    capability_request = request.get("project_root")
    if capability_request is None:
        return session
    if not isinstance(capability_request, dict) or capability_request.get("scope") != "app_data":
        raise AppHostingError("Runtime project root requires the app_data capability scope.")
    relative_path = capability_request.get("relative_path")
    app_data_root = Path(data_root)
    if not app_data_root.is_absolute():
        app_data_root = start_path / app_data_root
    store = getattr(state, "runtime_root_capabilities", None)
    if store is None:
        raise AppHostingError("Runtime root capability service is unavailable.")
    capability = store.issue(
        workspace_id=workspace_id,
        source_app_id=app_id,
        actor_id=actor_id,
        app_data_root=app_data_root,
        relative_path=relative_path,
        ttl_seconds=5,
    )
    resolved = store.consume(
        capability,
        workspace_id=workspace_id,
        source_app_id=app_id,
        actor_id=actor_id,
    )
    try:
        resolved.relative_to(Path(session.workspace_root).resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise AppHostingError("Runtime project root is outside the workspace boundary.") from exc
    return state.runtime_store.patch_session_metadata(
        session_id=session.session_id,
        workspace_id=workspace_id,
        updates={"workdir": str(resolved)},
    )


def _runtime_request_fingerprint(request: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in request.items()
        if key not in {"callback", "result_visibility"}
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
    return sha256(encoded).hexdigest()


def _validated_attachment_storage_path(item: dict[str, object]) -> str:
    raw_path = item.get("workspace_relative_path") or item.get("relative_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise AppHostingError("Runtime launch request attachments require workspace_relative_path or relative_path.")
    posix_path = PurePosixPath(raw_path.strip())
    if posix_path.is_absolute() or ".." in posix_path.parts:
        raise AppHostingError("Runtime launch request attachment paths must be workspace-relative Storage paths.")
    parts = tuple(posix_path.parts)
    if len(parts) < 3 or parts[:2] not in ATTACHMENT_STORAGE_PREFIXES:
        raise AppHostingError("Runtime launch request attachment paths must be under storage/uploaded or storage/generated.")
    return posix_path.as_posix()


def _require_attachment_inside_storage(candidate: Path, *, paths, relative_path: str) -> None:
    storage_roots = (paths.uploaded_storage.resolve(), paths.generated_storage.resolve())
    for root in storage_roots:
        try:
            candidate.relative_to(root)
            return
        except ValueError:
            continue
    raise AppHostingError(f"Runtime launch request attachment `{relative_path}` is outside workspace storage.")


def _runtime_attachment_payload(item: dict[str, object], *, relative_path: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "relative_path": relative_path,
        "workspace_relative_path": relative_path,
    }
    attachment_id = _text(item.get("id"))
    if attachment_id:
        payload["id"] = attachment_id
    name = _text(item.get("name") or item.get("filename"))
    if name:
        payload["name"] = name
    content_type = _text(item.get("content_type") or item.get("type"))
    if content_type:
        payload["content_type"] = content_type
    size = _validated_attachment_size(item)
    if size is not None:
        payload["size_bytes"] = size
    return payload


def _validated_attachment_size(item: dict[str, object]) -> int | None:
    value = item.get("size_bytes")
    if value is None:
        value = item.get("size")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AppHostingError("Runtime launch request attachment size_bytes must be numeric.")
    try:
        size = int(value)
    except (OverflowError, ValueError) as exc:
        raise AppHostingError("Runtime launch request attachment size_bytes must be a non-negative integer.") from exc
    if size < 0 or size != value:
        raise AppHostingError("Runtime launch request attachment size_bytes must be a non-negative integer.")
    return size


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
    if not runtime_session_allows_user_thread(session):
        raise AppHostingError(f"Runtime turn `{turn_id}` belongs to a hidden inter-agent session.")
    if session.source_app_id != app_id:
        raise AppHostingError(f"Runtime turn `{turn_id}` is owned by another source app.")
    if turn.status not in {"queued", "active"}:
        return {
            "turn_id": turn_id,
            "status": turn.status,
            "interrupted": False,
            "_visible": request.get("result_visibility") != "internal",
        }
    reason = _long_text(request.get("reason")) or "Interrupted by app request."
    cancellation_request = request_runtime_turn_cancellation(
        state.runtime_store,
        turn_id=turn_id,
        reason=reason,
    )
    provider_id = None
    provider_interrupted = False
    if cancellation_request.cancellation_requested_at is not None:
        provider_id = _resolved_provider_id(state, session)
        provider_interrupted = interrupt_runtime_provider_turn(state, session)
    updated = transition_runtime_turn(state.runtime_store, turn_id=turn_id, target_status="cancelled", failure_reason=reason)
    if updated.status != "cancelled":
        return {
            "turn_id": updated.turn_id,
            "status": updated.status,
            "interrupted": False,
            "_visible": request.get("result_visibility") != "internal",
        }
    provider_interrupted_after_handoff = interrupt_runtime_provider_turn(
        state,
        state.runtime_store.get_session(updated.session_id),
        wait_for_termination=True,
    )
    provider_interrupted = provider_interrupted_after_handoff or provider_interrupted
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
    set_thread_availability(
        state,
        workspace_id=updated.workspace_id,
        runtime_session_id=updated.session_id,
        availability="free",
        now=event.created_at,
    )
    release_idle_runtime_processes(state, session_id=updated.session_id, provider_id=provider_id or "unconfigured", reason="app_turn_interrupted", idle_ttl_seconds=0)
    dispatch_source_app_runtime_event(
        state,
        session=session,
        turn=updated,
        event_type="runtime.turn.cancelled",
        failure_reason=reason,
    )
    return {
        "turn_id": updated.turn_id,
        "status": updated.status,
        "interrupted": True,
        "provider_interrupted": provider_interrupted,
        "event_id": event.event_id,
        "_visible": request.get("result_visibility") != "internal",
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
    provider_app_id: str | None = None,
    user=None,
) -> dict[str, Any]:
    if not dependency_alias:
        raise AppHostingError("Dependency backend request requires dependency_alias.")
    dependencies = resolve_app_dependencies(
        state.app_store,
        workspace_id=workspace_id,
        consumer_app_id=app_id,
        user=user,
        workspace_store=state.workspace_store,
        start_path=start_path,
    )
    dependency = next(
        (item for item in dependencies.get("dependencies", []) if item.get("alias") == dependency_alias),
        None,
    )
    if not isinstance(dependency, dict):
        raise AppHostingError(f"Dependency alias `{dependency_alias}` is not declared by app `{app_id}`.")
    dependency_status = str(dependency.get("status") or "").strip()
    requested_provider_id = str(provider_app_id or "").strip()
    provider_ids = dependency.get("selected_provider_app_ids") if isinstance(dependency, dict) else []
    selected_provider_ids = (
        [str(item).strip() for item in provider_ids if str(item).strip()]
        if isinstance(provider_ids, list)
        else []
    )
    if dependency_status and dependency_status != "resolved" and (
        dependency_status != "optional_unset" or not requested_provider_id
    ):
        blocked_reason = str(dependency.get("blocked_reason") or dependency_status).strip()
        raise AppHostingError(f"Dependency alias `{dependency_alias}` is not resolved: {blocked_reason}.")
    if requested_provider_id and selected_provider_ids and requested_provider_id not in selected_provider_ids:
        raise AppHostingError(
            f"Dependency provider `{requested_provider_id}` is not selected for alias `{dependency_alias}`."
        )
    provider_id = requested_provider_id or (selected_provider_ids[0] if selected_provider_ids else "")
    if not provider_id:
        raise AppHostingError(f"Dependency alias `{dependency_alias}` has no selected provider app.")
    candidate = _dependency_candidate_for_provider(dependency, provider_id)
    if candidate is None or "backend" not in _dependency_candidate_surfaces(candidate):
        raise AppHostingError(f"Dependency provider `{provider_id}` does not declare backend surface for alias `{dependency_alias}`.")
    try:
        binding = state.app_store.get_workspace_app_binding(workspace_id=workspace_id, app_id=provider_id)
        provider_source_root, provider_parsed = resolve_workspace_app_surface(state.app_store, binding=binding, start_path=start_path)
    except WorkspaceAppBindingNotFoundError as exc:
        raise AppHostingError(f"Dependency provider `{provider_id}` is not enabled.") from exc
    backend = provider_parsed.contract.entrypoints.backend
    if backend is None:
        raise AppHostingError(f"Dependency provider `{provider_id}` does not expose a backend.")
    paths = workspace_paths(workspace_id, start_path=start_path)
    provider_secret_requests = _dependency_backend_provider_secret_requests(
        provider_source_root=provider_source_root,
        provider_backend=backend,
        workspace_id=workspace_id,
        provider_id=provider_id,
        consumer_app_id=app_id,
        dependency_alias=dependency_alias,
        data_root=binding.data_root,
        workspace_root=str(paths.root),
        uploaded_storage_root=str(paths.uploaded_storage),
        generated_storage_root=str(paths.generated_storage),
        declared_logical_names=provider_parsed.contract.permissions.secrets.read,
        body=body,
    )
    secret_requests = _dedupe_secret_requests(
        [
            *provider_secret_requests,
            *_dependency_backend_secret_requests(
                declared_logical_names=provider_parsed.contract.permissions.secrets.read,
                body=body,
            ),
        ]
    )
    try:
        app_secret_result = resolve_app_secret_payload_requests(
            getattr(state, "secret_store", None),
            workspace_id=workspace_id,
            app_id=provider_id,
            requests=secret_requests,
            surface="backend",
            runtime_session_id="",
            actor_user_id=None,
            observability_store=getattr(state, "observability_store", None),
            request_context={
                "surface": "dependency_backend",
                "consumer_app_id": app_id,
                "provider_app_id": provider_id,
                "dependency_alias": dependency_alias,
            },
            fail_closed=_dependency_backend_secrets_fail_closed(body, secret_requests=provider_secret_requests),
        )
    except SecretError as exc:
        raise AppHostingError(f"Dependency provider `{provider_id}` secret delivery failed: {exc}") from exc
    result = run_json_entrypoint(
        provider_source_root / backend,
        payload={
            "surface": "dependency_backend",
            "workspace_id": workspace_id,
            "app_id": provider_id,
            "consumer_app_id": app_id,
            "dependency_alias": dependency_alias,
            "workspace_root": str(paths.root),
            "data_root": binding.data_root,
            "uploaded_storage_root": str(paths.uploaded_storage),
            "generated_storage_root": str(paths.generated_storage),
            "app_secrets": app_secret_result.secrets,
            "app_secret_errors": app_secret_result.errors,
            "provider_config": _dependency_provider_config(
                state,
                workspace_id=workspace_id,
                provider_id=provider_id,
                interface=str(dependency.get("interface") or ""),
            ),
            "effective_mode": "full-access",
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
    result["dependency_provider_app_id"] = provider_id
    return result


def _dependency_candidate_for_provider(dependency: dict[str, Any], provider_id: str) -> dict[str, Any] | None:
    candidates = dependency.get("candidates")
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if isinstance(candidate, dict) and str(candidate.get("app_id") or "").strip() == provider_id:
            return candidate
    return None


def _dependency_candidate_surfaces(candidate: dict[str, Any]) -> set[str]:
    raw_surfaces = candidate.get("surfaces")
    if not isinstance(raw_surfaces, list):
        return set()
    return {str(item).strip() for item in raw_surfaces if str(item).strip()}


def _dependency_provider_config(
    state,
    *,
    workspace_id: str,
    provider_id: str,
    interface: str,
) -> dict[str, Any]:
    if provider_id != "speech" or interface != "speech.transcription":
        return {}
    from core.api.provider_api import workspace_speech_stt_backend_provider_config

    try:
        speech_stt = workspace_speech_stt_backend_provider_config(state, workspace_id=workspace_id)
    except ProviderError:
        return {}
    return {"speech_stt": speech_stt} if speech_stt else {}


def _dependency_backend_provider_secret_requests(
    *,
    provider_source_root: Path,
    provider_backend: str,
    workspace_id: str,
    provider_id: str,
    consumer_app_id: str,
    dependency_alias: str,
    data_root: str,
    workspace_root: str,
    uploaded_storage_root: str,
    generated_storage_root: str,
    declared_logical_names: list[str],
    body: dict[str, Any],
) -> list[AppSecretRequest]:
    if not any(str(item).strip() for item in declared_logical_names):
        return []
    result = run_json_entrypoint(
        provider_source_root / provider_backend,
        payload={
            "surface": "secret_selector",
            "workspace_id": workspace_id,
            "app_id": provider_id,
            "consumer_app_id": consumer_app_id,
            "dependency_alias": dependency_alias,
            "workspace_root": workspace_root,
            "data_root": data_root,
            "uploaded_storage_root": uploaded_storage_root,
            "generated_storage_root": generated_storage_root,
            "app_secrets": {},
            "app_secret_errors": [],
            "effective_mode": "full-access",
            "body": body,
            "runtime_session_id": "",
            "turn_id": "",
        },
        cwd=provider_source_root,
        timeout_seconds=30,
    )
    status_code = int(result.get("status_code", 200)) if isinstance(result, dict) else 200
    if status_code >= 400:
        raise AppHostingError(f"Dependency provider `{provider_id}` secret selector failed.")
    selector_result = result.get("json") if isinstance(result.get("json"), dict) else result
    if not isinstance(selector_result, dict) or not bool(selector_result.get("requires_secrets")):
        return []
    declared = {str(item).strip().lower() for item in declared_logical_names if str(item).strip()}
    requests = _secret_requests_from_selector_result(selector_result, declared=declared)
    if not requests:
        raise AppHostingError(f"Dependency provider `{provider_id}` secret selector did not declare required logical names.")
    return requests


def _secret_requests_from_selector_result(result: dict[str, Any], *, declared: set[str]) -> list[AppSecretRequest]:
    raw_requests = result.get("secret_requests")
    if isinstance(raw_requests, list):
        requests: list[AppSecretRequest] = []
        for item in raw_requests:
            if not isinstance(item, dict):
                continue
            logical_names = _dependency_secret_names(item.get("logical_names", []), declared=declared)
            if not logical_names:
                continue
            resource_type, resource_id = _dependency_secret_resource(item)
            requests.append(AppSecretRequest(logical_names=logical_names, resource_type=resource_type, resource_id=resource_id))
        return requests
    logical_names = _dependency_secret_names(result.get("logical_names", []), declared=declared)
    if not logical_names:
        return []
    resource_type, resource_id = _dependency_secret_resource(result)
    return [AppSecretRequest(logical_names=logical_names, resource_type=resource_type, resource_id=resource_id)]


def _dependency_backend_secret_requests(*, declared_logical_names: list[str], body: dict[str, Any]) -> list[AppSecretRequest]:
    request = body.get("_app_secret_request")
    declared = {str(item).strip().lower() for item in declared_logical_names if str(item).strip()}
    if not isinstance(request, dict):
        return []
    raw_selectors = request.get("selectors")
    if isinstance(raw_selectors, list):
        selectors: list[AppSecretRequest] = []
        for item in raw_selectors:
            if not isinstance(item, dict):
                continue
            logical_names = _dependency_secret_names(item.get("logical_names", []), declared=declared)
            if not logical_names:
                continue
            resource_type, resource_id = _dependency_secret_resource(item)
            selectors.append(AppSecretRequest(logical_names=logical_names, resource_type=resource_type, resource_id=resource_id))
        return selectors
    logical_names = _dependency_secret_names(request.get("logical_names", []), declared=declared)
    if not logical_names:
        return []
    resource_type, resource_id = _dependency_secret_resource(request)
    return [AppSecretRequest(logical_names=logical_names, resource_type=resource_type, resource_id=resource_id)]


def _dependency_secret_names(raw_names: object, *, declared: set[str]) -> list[str]:
    if not isinstance(raw_names, list):
        return []
    names: list[str] = []
    for item in raw_names:
        logical_name = str(item).strip().lower()
        if logical_name in declared and logical_name not in names:
            names.append(logical_name)
    return names


def _dependency_secret_resource(request: dict[str, Any]) -> tuple[str | None, str | None]:
    resource_type = str(request.get("resource_type") or "").strip().lower()
    resource_id = str(request.get("resource_id") or "").strip().lower()
    if not resource_type or not resource_id:
        return None, None
    return resource_type, resource_id


def _dedupe_secret_requests(requests: list[AppSecretRequest]) -> list[AppSecretRequest]:
    deduped: list[AppSecretRequest] = []
    seen: set[tuple[tuple[str, ...], str | None, str | None]] = set()
    for request in requests:
        key = (tuple(request.logical_names), request.resource_type, request.resource_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(request)
    return deduped


def _dependency_backend_secrets_fail_closed(body: dict[str, Any], *, secret_requests: list[AppSecretRequest]) -> bool:
    request = body.get("_app_secret_request")
    if secret_requests:
        return True
    if not isinstance(request, dict):
        return False
    return bool(request.get("required"))


def _safe_dependency_backend_request_callback(*args, **kwargs) -> dict[str, Any]:
    try:
        return _invoke_dependency_backend_request_callback(*args, **kwargs)
    except Exception:
        return {"status_code": 0}


def _invoke_dependency_backend_request_callback(
    state,
    *,
    callback: dict[str, Any],
    workspace_id: str,
    app_id: str,
    source_root: Path,
    backend_entrypoint: str | None,
    data_root: str,
    parsed: ParsedAppContract,
    request: dict[str, Any],
    request_id: str,
    dependency_alias: str,
    status: str,
    provider_result: dict[str, Any],
    error: str,
    start_path: Path,
    actor_user_id: str | None,
) -> dict[str, Any]:
    action = _text(callback.get("action"))
    if not action or backend_entrypoint is None:
        return {}
    payload = callback.get("payload") if isinstance(callback.get("payload"), dict) else {}
    paths = workspace_paths(workspace_id, start_path=start_path)
    from core.api.sidecar_entrypoint_invocation import run_json_entrypoint_with_sidecars

    binding = state.app_store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    result = run_json_entrypoint_with_sidecars(
        source_root / backend_entrypoint,
        payload={
            "surface": "dependency_backend_request_callback",
            "workspace_id": workspace_id,
            "app_id": app_id,
            "workspace_root": str(paths.root),
            "data_root": data_root,
            "uploaded_storage_root": str(paths.uploaded_storage),
            "generated_storage_root": str(paths.generated_storage),
            "body": {
                **payload,
                "action": action,
                "request_id": request_id,
                "dependency_alias": dependency_alias,
                "dependency_backend_status": status,
                "dependency_backend_result": provider_result,
                "error": error,
                "request": request,
            },
            "runtime_session_id": "",
            "turn_id": "",
        },
        cwd=source_root,
        binding=binding,
        parsed=parsed,
        surface="backend",
        start_path=start_path,
        actor_user_id=actor_user_id,
        runtime_session_id=None,
        observability_store=state.observability_store,
        timeout_seconds=int(parsed.contract.hook_timeouts.backend_seconds),
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
    stream_id: str,
    actor_id: str,
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
                "stream_id": stream_id,
                "actor_id": actor_id,
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
