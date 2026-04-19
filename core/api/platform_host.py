"""Minimal hosted platform HTTP surface for Maverick v3."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import parse_qs
from uuid import uuid4

from core.api.platform_state import PlatformState
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.providers.service import resolve_provider_for_runtime_session
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.service import create_runtime_session, queue_runtime_turn, transition_runtime_session, transition_runtime_turn
from core.shared.entrypoints import run_json_entrypoint
from core.workspaces.paths import workspace_paths

StartResponse = Callable[[str, list[tuple[str, str]]], None]


def _status_line(status_code: int) -> str:
    reasons = {
        200: "OK",
        400: "Bad Request",
        404: "Not Found",
        500: "Internal Server Error",
    }
    return f"{status_code} {reasons.get(status_code, 'OK')}"


def _json_response(start_response: StartResponse, payload: dict, *, status: str = "200 OK") -> list[bytes]:
    body = json.dumps(payload, indent=2).encode("utf-8")
    start_response(status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))])
    return [body]


def _text_response(start_response: StartResponse, body: str, *, status: str = "200 OK", content_type: str = "text/plain; charset=utf-8") -> list[bytes]:
    encoded = body.encode("utf-8")
    start_response(status, [("Content-Type", content_type), ("Content-Length", str(len(encoded)))])
    return [encoded]


def _read_body(environ: dict) -> dict:
    length = int(environ.get("CONTENT_LENGTH") or "0")
    raw = environ["wsgi.input"].read(length) if length > 0 else b""
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _enabled_app_items(state: PlatformState, *, workspace_id: str, start_path: Path) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for binding in enabled_workspace_app_bindings(state.app_store, workspace_id=workspace_id):
        source_root, parsed = resolve_workspace_app_surface(state.app_store, binding=binding, start_path=start_path)
        items.append(
            {
                "app_id": parsed.app_id,
                "name": parsed.name,
                "version": parsed.version,
                "status": binding.status,
                "distribution_mode": parsed.contract.distribution.mode,
                "source_access": parsed.contract.distribution.source_access,
                "frontend_mount": f"/apps/{parsed.app_id}/" if parsed.contract.entrypoints.frontend else "",
                "backend_mount": f"/api/apps/{parsed.app_id}/backend" if parsed.contract.entrypoints.backend else "",
            }
        )
    return items


def _resolve_app(state: PlatformState, *, workspace_id: str, app_id: str, start_path: Path):
    binding = state.app_store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    return binding, *resolve_workspace_app_surface(state.app_store, binding=binding, start_path=start_path)


def _ensure_runtime_session(state: PlatformState, *, workspace_id: str, app_id: str, start_path: Path):
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


def _serve_frontend(start_response: StartResponse, *, frontend_root: Path, subpath: str) -> list[bytes]:
    candidate = (frontend_root / subpath.lstrip("/")).resolve() if subpath.strip("/") else (frontend_root / "index.html").resolve()
    if candidate == frontend_root.resolve() or frontend_root.resolve() not in candidate.parents:
        return _text_response(start_response, "Not found", status="404 Not Found")
    if candidate.is_dir():
        candidate = candidate / "index.html"
    if not candidate.exists():
        candidate = frontend_root / "index.html"
    body = candidate.read_bytes()
    content_type = mimetypes.guess_type(str(candidate))[0] or "text/html; charset=utf-8"
    start_response("200 OK", [("Content-Type", content_type), ("Content-Length", str(len(body)))])
    return [body]


class PlatformHost:
    """Serve mounted app frontends and backends behind the core host."""

    def __init__(self, state: PlatformState, *, workspace_id: str = "default", start_path: Path | None = None) -> None:
        self.state = state
        self.workspace_id = workspace_id
        self.start_path = start_path or state.repository_root

    def __call__(self, environ: dict, start_response: StartResponse) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "/")
        method = environ.get("REQUEST_METHOD", "GET").upper()

        if path == "/health":
            return _json_response(start_response, {"status": "ok", "service": "maverick3-core"})
        if path == "/api/status":
            return _json_response(
                start_response,
                {
                    "status": "ok",
                    "workspace_id": self.workspace_id,
                    "apps": _enabled_app_items(self.state, workspace_id=self.workspace_id, start_path=self.start_path),
                },
            )
        if path == "/api/apps":
            return _json_response(
                start_response,
                {"items": _enabled_app_items(self.state, workspace_id=self.workspace_id, start_path=self.start_path)},
            )
        if path == "/":
            _binding, source_root, parsed = _resolve_app(self.state, workspace_id=self.workspace_id, app_id="base-shell", start_path=self.start_path)
            return _serve_frontend(
                start_response,
                frontend_root=(source_root / parsed.contract.entrypoints.frontend).resolve(),
                subpath="/",
            )
        if path.startswith("/apps/"):
            app_path = path.removeprefix("/apps/")
            app_id, _, subpath = app_path.partition("/")
            _binding, source_root, parsed = _resolve_app(
                self.state,
                workspace_id=self.workspace_id,
                app_id=app_id,
                start_path=self.start_path,
            )
            frontend = parsed.contract.entrypoints.frontend
            if frontend is None:
                return _text_response(start_response, "App frontend not found", status="404 Not Found")
            return _serve_frontend(start_response, frontend_root=(source_root / frontend).resolve(), subpath=subpath)
        if path.startswith("/api/apps/") and path.endswith("/backend") and method == "POST":
            app_id = path.removeprefix("/api/apps/").removesuffix("/backend").strip("/")
            binding, source_root, parsed = _resolve_app(
                self.state,
                workspace_id=self.workspace_id,
                app_id=app_id,
                start_path=self.start_path,
            )
            backend = parsed.contract.entrypoints.backend
            if backend is None:
                return _text_response(start_response, "App backend not found", status="404 Not Found")
            body = _read_body(environ)
            session = _ensure_runtime_session(self.state, workspace_id=self.workspace_id, app_id=app_id, start_path=self.start_path)
            turn_id = f"{session.session_id}:{uuid4().hex[:8]}"
            queue_runtime_turn(self.state.runtime_store, turn_id=turn_id, session_id=session.session_id, input_text=str(body.get("message") or body.get("action") or ""))
            transition_runtime_turn(self.state.runtime_store, turn_id=turn_id, target_status="active")
            provider, _selection = resolve_provider_for_runtime_session(self.state.provider_store, session=session)
            paths = workspace_paths(self.workspace_id, start_path=self.start_path)
            try:
                result = run_json_entrypoint(
                    source_root / backend,
                    payload={
                        "surface": "backend",
                        "workspace_id": self.workspace_id,
                        "app_id": app_id,
                        "workspace_root": str(paths.root),
                        "data_root": binding.data_root,
                        "uploaded_storage_root": str(paths.uploaded_storage),
                        "generated_storage_root": str(paths.generated_storage),
                        "route_path": path,
                        "method": method,
                        "query": {key: value[-1] for key, value in parse_qs(environ.get("QUERY_STRING", "")).items()},
                        "headers": {
                            "content_type": environ.get("CONTENT_TYPE", ""),
                        },
                        "body": body,
                        "provider_id": provider.provider_id,
                        "runtime_session_id": session.session_id,
                        "turn_id": turn_id,
                    },
                    cwd=source_root,
                )
                transition_runtime_turn(self.state.runtime_store, turn_id=turn_id, target_status="completed")
            except Exception as error:
                transition_runtime_turn(
                    self.state.runtime_store,
                    turn_id=turn_id,
                    target_status="failed",
                    failure_reason=str(error),
                )
                return _json_response(start_response, {"error": str(error)}, status=_status_line(500))
            status_code = int(result.get("status_code", 200))
            if "json" in result:
                return _json_response(start_response, result["json"], status=_status_line(status_code))
            if "body" in result:
                return _text_response(start_response, str(result["body"]), status=_status_line(status_code))
            return _json_response(start_response, result, status=_status_line(status_code))
        return _text_response(start_response, "Not found", status="404 Not Found")
