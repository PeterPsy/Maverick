"""Dispatch runtime terminal events to source apps that opt in."""

from __future__ import annotations

from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from core.api.app_event_publication import declared_data_event_resources, publish_declared_app_events
from core.apps.dependencies import resolve_app_dependencies
from core.apps.errors import AppHostingError
from core.apps.surfaces import (
    WorkspaceAppSurfaceCache,
    enabled_workspace_app_bindings,
    resolve_workspace_app_surface,
)
from core.runtime.service import record_runtime_event
from core.shared.entrypoints import run_json_entrypoint
from core.workspaces.paths import workspace_paths

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState
    from core.runtime.runtime_session import RuntimeSessionRecord
    from core.runtime.runtime_turns import RuntimeTurnRecord


def dispatch_source_app_runtime_event_async(
    state: "PlatformState",
    *,
    session: "RuntimeSessionRecord",
    turn: "RuntimeTurnRecord",
    event_type: str,
    output_text: str = "",
    failure_reason: str = "",
    start_path: Path | None = None,
) -> bool:
    """Schedule a source app runtime hook without keeping the turn worker on the hook path."""
    if not (session.source_app_id or "").strip():
        return False

    def run() -> None:
        try:
            dispatch_source_app_runtime_event(
                state,
                session=session,
                turn=turn,
                event_type=event_type,
                output_text=output_text,
                failure_reason=failure_reason,
                start_path=start_path,
            )
        except Exception as error:
            _record_source_app_hook_failure(state, session=session, turn=turn, detail=str(error))

    Thread(target=run, name=f"runtime-source-app-hook-{event_type}", daemon=True).start()
    return True


def dispatch_source_app_runtime_event(
    state: "PlatformState",
    *,
    session: "RuntimeSessionRecord",
    turn: "RuntimeTurnRecord",
    event_type: str,
    output_text: str = "",
    failure_reason: str = "",
    runtime_event_id: str | None = None,
    raise_on_failure: bool = False,
    start_path: Path | None = None,
) -> dict[str, Any] | None:
    """Notify the source app for a terminal runtime turn when it declares a runtime hook."""
    app_id = (session.source_app_id or "").strip()
    if not app_id:
        return None
    try:
        binding = state.app_store.get_workspace_app_binding(workspace_id=session.workspace_id, app_id=app_id)
        if binding.status != "enabled":
            return None
        source_root, parsed = resolve_workspace_app_surface(state.app_store, binding=binding, start_path=start_path)
    except AppHostingError:
        return None
    hook_path = parsed.contract.entrypoints.hooks.get("runtime_event")
    if not hook_path:
        return None
    paths = workspace_paths(session.workspace_id, start_path=start_path)
    payload = {
        "surface": "runtime_event",
        "workspace_id": session.workspace_id,
        "app_id": app_id,
        "workspace_root": str(paths.root),
        "data_root": binding.data_root,
        "uploaded_storage_root": str(paths.uploaded_storage),
        "generated_storage_root": str(paths.generated_storage),
        "runtime_session_id": session.session_id,
        "turn_id": turn.turn_id,
        "app_dependencies": _app_dependencies_payload(
            state,
            workspace_id=session.workspace_id,
            app_id=app_id,
            start_path=start_path,
        ),
        "body": {
            "action": event_type,
            "runtime_session_id": session.session_id,
            "turn_id": turn.turn_id,
            "turn_status": turn.status,
            "output_text": output_text,
            "failure_reason": failure_reason or turn.failure_reason or "",
            "agent_id": session.agent_id,
            "source_app_id": app_id,
            "runtime_event_id": runtime_event_id or "",
        },
    }
    try:
        from core.api.sidecar_entrypoint_invocation import run_json_entrypoint_with_sidecars

        result = run_json_entrypoint_with_sidecars(
            source_root / hook_path,
            payload=payload,
            cwd=source_root,
            binding=binding,
            parsed=parsed,
            surface="backend",
            start_path=start_path or state.repository_root,
            actor_user_id=session.owner_user_id,
            runtime_session_id=session.session_id,
            observability_store=state.observability_store,
            timeout_seconds=30,
        )
    except Exception as error:
        _record_source_app_hook_failure(state, session=session, turn=turn, detail=str(error))
        if raise_on_failure:
            raise
        return None
    publish_declared_app_events(
        state.app_event_bus,
        result,
        workspace_id=session.workspace_id,
        app_id=app_id,
        declared_resources=declared_data_event_resources(parsed.contract.capabilities.data_events),
        remove_from_result=True,
    )
    _apply_runtime_requests(
        state,
        result=result,
        workspace_id=session.workspace_id,
        app_id=app_id,
        source_root=source_root,
        backend_entrypoint=parsed.contract.entrypoints.backend,
        data_root=binding.data_root,
        parsed=parsed,
        start_path=start_path,
        actor_user_id=session.owner_user_id,
    )
    return result


def _record_source_app_hook_failure(
    state: "PlatformState",
    *,
    session: "RuntimeSessionRecord",
    turn: "RuntimeTurnRecord",
    detail: str,
) -> None:
    try:
        record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session.session_id,
            turn_id=turn.turn_id,
            plane="runtime",
            event_type="runtime.source_app_hook.failed",
            payload={"source_app_id": session.source_app_id or "", "hook": "runtime_event", "detail": detail},
            event_bus=state.runtime_event_bus,
        )
    except Exception:
        return


def dispatch_workspace_app_background_hooks(
    state: "PlatformState",
    *,
    workspace_id: str,
    hook_name: str,
    action: str,
    body: dict[str, Any] | None = None,
    start_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Invoke one generic background hook on enabled workspace apps that declare it."""
    results: list[dict[str, Any]] = []
    bindings = enabled_workspace_app_bindings(
        state.app_store,
        workspace_id=workspace_id,
    )
    surface_cache: WorkspaceAppSurfaceCache = {}
    for binding in bindings:
        if binding.status != "enabled":
            continue
        try:
            source_root, parsed = resolve_workspace_app_surface(
                state.app_store,
                binding=binding,
                start_path=start_path,
                surface_cache=surface_cache,
            )
        except AppHostingError:
            continue
        except Exception as error:
            results.append({"app_id": binding.app_id, "status": "failed", "detail": str(error)})
            continue
        try:
            result = _dispatch_workspace_app_background_hook(
                state,
                binding=binding,
                source_root=source_root,
                parsed=parsed,
                workspace_id=workspace_id,
                hook_name=hook_name,
                action=action,
                body=body,
                start_path=start_path,
                workspace_bindings=bindings,
                surface_cache=surface_cache,
            )
        except Exception as error:
            results.append({"app_id": binding.app_id, "status": "failed", "detail": str(error)})
            continue
        if result is None:
            continue
        results.append({"app_id": binding.app_id, "status": "completed", "result": result})
    return results


def _dispatch_workspace_app_background_hook(
    state: "PlatformState",
    *,
    binding,
    source_root: Path,
    parsed,
    workspace_id: str,
    hook_name: str,
    action: str,
    body: dict[str, Any] | None,
    start_path: Path | None,
    workspace_bindings,
    surface_cache: WorkspaceAppSurfaceCache,
) -> dict[str, Any] | None:
    hook_path = parsed.contract.entrypoints.hooks.get(hook_name)
    if not hook_path:
        return None
    paths = workspace_paths(workspace_id, start_path=start_path)
    payload = {
        "surface": hook_name,
        "workspace_id": workspace_id,
        "app_id": binding.app_id,
        "workspace_root": str(paths.root),
        "data_root": binding.data_root,
        "uploaded_storage_root": str(paths.uploaded_storage),
        "generated_storage_root": str(paths.generated_storage),
        "runtime_session_id": "",
        "turn_id": "",
        "app_dependencies": _app_dependencies_payload(
            state,
            workspace_id=workspace_id,
            app_id=binding.app_id,
            start_path=start_path,
            workspace_bindings=workspace_bindings,
            surface_cache=surface_cache,
        ),
        "body": {"action": action, **(body or {})},
    }
    result = run_json_entrypoint(source_root / hook_path, payload=payload, cwd=source_root, timeout_seconds=30)
    publish_declared_app_events(
        state.app_event_bus,
        result,
        workspace_id=workspace_id,
        app_id=binding.app_id,
        declared_resources=declared_data_event_resources(parsed.contract.capabilities.data_events),
        remove_from_result=True,
    )
    _apply_runtime_requests(
        state,
        result=result,
        workspace_id=workspace_id,
        app_id=binding.app_id,
        source_root=source_root,
        backend_entrypoint=parsed.contract.entrypoints.backend,
        data_root=binding.data_root,
        parsed=parsed,
        start_path=start_path,
    )
    return result


def _app_dependencies_payload(
    state: "PlatformState",
    *,
    workspace_id: str,
    app_id: str,
    start_path: Path | None,
    workspace_bindings=None,
    surface_cache: WorkspaceAppSurfaceCache | None = None,
) -> dict[str, object]:
    try:
        return resolve_app_dependencies(
            state.app_store,
            workspace_id=workspace_id,
            consumer_app_id=app_id,
            workspace_store=state.workspace_store,
            start_path=start_path,
            workspace_bindings=workspace_bindings,
            surface_cache=surface_cache,
        )
    except Exception:
        return {"workspace_id": workspace_id, "consumer_app_id": app_id, "status": "blocked", "dependencies": []}


def _apply_runtime_requests(
    state: "PlatformState",
    *,
    result: dict[str, Any],
    workspace_id: str,
    app_id: str,
    source_root: Path,
    backend_entrypoint: str | None,
    data_root: str,
    parsed,
    start_path: Path | None,
    actor_user_id: str | None = None,
) -> None:
    from core.apps.runtime_requests import apply_app_runtime_requests

    apply_app_runtime_requests(
        state,
        result=result,
        workspace_id=workspace_id,
        app_id=app_id,
        source_root=source_root,
        backend_entrypoint=backend_entrypoint,
        data_root=data_root,
        parsed=parsed,
        start_path=start_path or state.repository_root,
        actor_user_id=actor_user_id,
    )
