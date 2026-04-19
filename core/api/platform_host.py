"""Hosted platform HTTP surface for Maverick v3."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from core.api.app_mounts import handle_app_backend, handle_app_frontend, handle_root_shell
from core.api.app_registry import enabled_app_items
from core.api.http import StartResponse, json_response, text_response
from core.api.platform_state import PlatformState
from core.api.provider_api import handle_provider_api
from core.api.runtime_api import handle_runtime_api
from core.api.session_api import handle_session_api, resolve_request_session
from core.api.settings_api import handle_settings_api
from core.api.widget_api import handle_widget_api
from core.api.workspace_files_api import handle_workspace_files_api
from core.api.workspace_api import handle_workspace_api


class PlatformHost:
    """Serve the shell, mounted apps, and shell-facing core APIs."""

    def __init__(self, state: PlatformState, *, workspace_id: str = "default", start_path: Path | None = None) -> None:
        self.state = state
        self.workspace_id = workspace_id
        self.start_path = start_path or state.repository_root

    def _request_workspace_id(self, environ: dict) -> str:
        context = resolve_request_session(self.state, environ)
        return context.workspace_id if context is not None else self.workspace_id

    def __call__(self, environ: dict, start_response: StartResponse) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "/")
        method = environ.get("REQUEST_METHOD", "GET").upper()
        workspace_id = self._request_workspace_id(environ)

        routed = handle_session_api(self.state, environ, start_response)
        if routed is not None:
            return routed
        routed = handle_workspace_api(self.state, environ, start_response, start_path=self.start_path)
        if routed is not None:
            return routed
        routed = handle_provider_api(self.state, environ, start_response)
        if routed is not None:
            return routed
        routed = handle_runtime_api(self.state, environ, start_response, start_path=self.start_path)
        if routed is not None:
            return routed
        routed = handle_settings_api(self.state, environ, start_response)
        if routed is not None:
            return routed
        routed = handle_workspace_files_api(self.state, environ, start_response, start_path=self.start_path)
        if routed is not None:
            return routed
        routed = handle_widget_api(self.state, environ, start_response, start_path=self.start_path)
        if routed is not None:
            return routed

        if path == "/health":
            return json_response(start_response, {"status": "ok", "service": "maverick3-core"})
        if path == "/favicon.ico":
            start_response("204 No Content", [("Content-Length", "0")])
            return [b""]
        if path == "/api/status":
            return json_response(
                start_response,
                {
                    "status": "ok",
                    "workspace_id": workspace_id,
                    "apps": enabled_app_items(self.state, workspace_id=workspace_id, start_path=self.start_path),
                },
            )
        if path == "/api/apps":
            return json_response(
                start_response,
                {"items": enabled_app_items(self.state, workspace_id=workspace_id, start_path=self.start_path)},
            )
        if path == "/":
            return handle_root_shell(
                self.state,
                workspace_id=workspace_id,
                start_path=self.start_path,
                start_response=start_response,
            )
        if path.startswith("/apps/"):
            app_path = path.removeprefix("/apps/")
            app_id, _, subpath = app_path.partition("/")
            return handle_app_frontend(
                self.state,
                workspace_id=workspace_id,
                app_id=app_id,
                subpath=subpath,
                start_path=self.start_path,
                start_response=start_response,
            )
        if path.startswith("/api/apps/") and path.endswith("/backend") and method == "POST":
            app_id = path.removeprefix("/api/apps/").removesuffix("/backend").strip("/")
            return handle_app_backend(
                self.state,
                environ=environ,
                workspace_id=workspace_id,
                app_id=app_id,
                start_path=self.start_path,
                start_response=start_response,
            )
        return text_response(start_response, "Not found", status="404 Not Found")
