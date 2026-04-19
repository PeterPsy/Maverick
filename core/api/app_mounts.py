"""Mounted app frontend and backend execution handlers."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from uuid import uuid4

from core.api.app_registry import resolve_app_surface
from core.api.http import StartResponse, json_response, query_params, read_json_body, status_line, text_response
from core.api.platform_state import PlatformState
from core.providers.service import resolve_provider_for_runtime_session
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.service import create_runtime_session, queue_runtime_turn, transition_runtime_session, transition_runtime_turn
from core.shared.entrypoints import run_json_entrypoint
from core.workspaces.paths import workspace_paths


def ensure_runtime_session(state: PlatformState, *, workspace_id: str, app_id: str, start_path: Path):
    """Ensure one UI-owned runtime session exists and is running for an app."""
    session_id = f"{workspace_id}:{app_id}:ui"
    try:
        session = state.runtime_store.get_session(session_id)
    except RuntimeSessionNotFoundError:
        governance = state.workspace_store.get_governance(workspace_id)
        session = create_runtime_session(
            state.runtime_store,
            session_id=session_id,
            workspace_id=workspace_id,
            agent_id=f"app-{app_id}",
            governance=governance,
            platform_allows_full_access=False,
            start_path=start_path,
            observability_store=state.observability_store,
        )
    if session.status != "running":
        session = transition_runtime_session(
            state.runtime_store,
            session_id=session.session_id,
            target_status="running",
            observability_store=state.observability_store,
            start_path=start_path,
        )
    return session


def serve_frontend(
    start_response: StartResponse,
    *,
    frontend_root: Path,
    subpath: str,
    spa_fallback: bool = True,
) -> list[bytes]:
    """Serve an app frontend asset, optionally falling back to index.html for SPA routes."""
    root = frontend_root.resolve()
    candidate = (root / subpath.lstrip("/")).resolve() if subpath.strip("/") else (root / "index.html").resolve()
    if candidate == root or root not in candidate.parents:
        return text_response(start_response, "Not found", status="404 Not Found")
    if candidate.is_dir():
        candidate = candidate / "index.html"
    if not candidate.exists():
        if not spa_fallback:
            return text_response(start_response, "Not found", status="404 Not Found")
        candidate = root / "index.html"
    if not candidate.exists() or not candidate.is_file():
        return text_response(start_response, "Not found", status="404 Not Found")
    body = candidate.read_bytes()
    content_type = mimetypes.guess_type(str(candidate))[0] or "text/html; charset=utf-8"
    start_response("200 OK", [("Content-Type", content_type), ("Content-Length", str(len(body)))])
    return [body]


def handle_root_shell(state: PlatformState, *, workspace_id: str, start_path: Path, start_response: StartResponse) -> list[bytes]:
    """Serve the configured root shell app for the active workspace."""
    _binding, source_root, parsed = resolve_app_surface(
        state,
        workspace_id=workspace_id,
        app_id="base-shell",
        start_path=start_path,
    )
    return serve_frontend(
        start_response,
        frontend_root=(source_root / parsed.contract.entrypoints.frontend).resolve(),
        subpath="/",
    )


def handle_app_frontend(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    subpath: str,
    start_path: Path,
    start_response: StartResponse,
) -> list[bytes]:
    """Serve one mounted app frontend."""
    _binding, source_root, parsed = resolve_app_surface(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        start_path=start_path,
    )
    frontend = parsed.contract.entrypoints.frontend
    if frontend is None:
        return text_response(start_response, "App frontend not found", status="404 Not Found")
    return serve_frontend(start_response, frontend_root=(source_root / frontend).resolve(), subpath=subpath)


def handle_app_backend(
    state: PlatformState,
    *,
    environ: dict,
    workspace_id: str,
    app_id: str,
    start_path: Path,
    start_response: StartResponse,
) -> list[bytes]:
    """Execute one app backend entrypoint through the platform runtime path."""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    binding, source_root, parsed = resolve_app_surface(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        start_path=start_path,
    )
    backend = parsed.contract.entrypoints.backend
    if backend is None:
        return text_response(start_response, "App backend not found", status="404 Not Found")
    body = read_json_body(environ)
    session = ensure_runtime_session(state, workspace_id=workspace_id, app_id=app_id, start_path=start_path)
    turn_id = f"{session.session_id}:{uuid4().hex[:8]}"
    queue_runtime_turn(
        state.runtime_store,
        turn_id=turn_id,
        session_id=session.session_id,
        input_text=str(body.get("message") or body.get("action") or ""),
    )
    transition_runtime_turn(state.runtime_store, turn_id=turn_id, target_status="active")
    provider, _selection = resolve_provider_for_runtime_session(state.provider_store, session=session)
    paths = workspace_paths(workspace_id, start_path=start_path)
    try:
        result = run_json_entrypoint(
            source_root / backend,
            payload={
                "surface": "backend",
                "workspace_id": workspace_id,
                "app_id": app_id,
                "workspace_root": str(paths.root),
                "data_root": binding.data_root,
                "uploaded_storage_root": str(paths.uploaded_storage),
                "generated_storage_root": str(paths.generated_storage),
                "route_path": environ.get("PATH_INFO", ""),
                "method": method,
                "query": query_params(environ),
                "headers": {"content_type": environ.get("CONTENT_TYPE", "")},
                "body": body,
                "provider_id": provider.provider_id,
                "runtime_session_id": session.session_id,
                "turn_id": turn_id,
            },
            cwd=source_root,
        )
        transition_runtime_turn(state.runtime_store, turn_id=turn_id, target_status="completed")
    except Exception as error:
        transition_runtime_turn(
            state.runtime_store,
            turn_id=turn_id,
            target_status="failed",
            failure_reason=str(error),
        )
        return json_response(start_response, {"error": str(error)}, status=status_line(500))
    status_code = int(result.get("status_code", 200))
    if "json" in result:
        return json_response(start_response, result["json"], status=status_line(status_code))
    if "body" in result:
        return text_response(start_response, str(result["body"]), status=status_line(status_code))
    return json_response(start_response, result, status=status_line(status_code))
