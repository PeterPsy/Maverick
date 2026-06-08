"""Hosted platform HTTP surface for Maverick."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from core.api.admin_api import handle_admin_api
from core.api.app_dependencies_api import handle_app_dependencies_api
from core.api.app_mounts import (
    handle_app_backend,
    handle_app_frontend,
    handle_app_frontend_build,
    handle_root_shell,
    handle_root_shell_static_asset,
    is_public_app_static_asset,
)
from core.api.app_references_api import handle_app_references_api
from core.api.app_registry import enabled_app_items
from core.api.app_sdk_api import handle_app_sdk_api
from core.api.app_store_api import handle_app_store_api
from core.api.http import HttpRequestError, StartResponse, enforce_same_origin_for_unsafe_request, json_response, text_response
from core.api.platform_state import PlatformState
from core.api.provider_api import handle_provider_api
from core.api.runtime_api import handle_runtime_api
from core.api.runtime_cli_api import handle_runtime_cli_api
from core.api.session_api import handle_session_api, resolve_request_session
from core.api.secret_api import handle_secret_api
from core.api.settings_api import handle_settings_api
from core.api.widget_api import handle_widget_api
from core.api.workspace_files_api import handle_workspace_files_api
from core.api.workspace_api import handle_workspace_api
from core.shared.entrypoints import EntrypointShutdownController


logger = logging.getLogger(__name__)


_ROOT_SHELL_STATIC_ASSETS = {
    "/manifest.webmanifest": "manifest.webmanifest",
    "/sw.js": "sw.js",
}


class PlatformHost:
    """Serve the shell, mounted apps, and shell-facing core APIs."""

    def __init__(
        self,
        state: PlatformState,
        *,
        workspace_id: str = "default",
        start_path: Path | None = None,
        shutdown_controller: EntrypointShutdownController | None = None,
    ) -> None:
        self.state = state
        self.workspace_id = workspace_id
        self.start_path = start_path or state.repository_root
        self.shutdown_controller = shutdown_controller

    def __call__(self, environ: dict, start_response: StartResponse) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "/")
        try:
            method = environ.get("REQUEST_METHOD", "GET").upper()
            enforce_same_origin_for_unsafe_request(environ)
            context = resolve_request_session(self.state, environ)
            workspace_id = context.workspace_id if context is not None else self.workspace_id
            user = context.user if context is not None else None

            routed = handle_session_api(self.state, environ, start_response)
            if routed is not None:
                return routed
            routed = handle_workspace_api(self.state, environ, start_response, start_path=self.start_path)
            if routed is not None:
                return routed
            routed = handle_admin_api(self.state, environ, start_response, start_path=self.start_path)
            if routed is not None:
                return routed
            routed = handle_app_store_api(self.state, environ, start_response, start_path=self.start_path)
            if routed is not None:
                return routed
            routed = handle_app_sdk_api(self.state, environ, start_response, start_path=self.start_path)
            if routed is not None:
                return routed
            routed = handle_provider_api(self.state, environ, start_response)
            if routed is not None:
                return routed
            routed = handle_runtime_cli_api(self.state, environ, start_response, start_path=self.start_path)
            if routed is not None:
                return routed
            routed = handle_runtime_api(self.state, environ, start_response, start_path=self.start_path)
            if routed is not None:
                return routed
            routed = handle_settings_api(self.state, environ, start_response)
            if routed is not None:
                return routed
            routed = handle_secret_api(self.state, environ, start_response)
            if routed is not None:
                return routed
            routed = handle_workspace_files_api(self.state, environ, start_response, start_path=self.start_path)
            if routed is not None:
                return routed
            routed = handle_app_dependencies_api(self.state, environ, start_response, start_path=self.start_path)
            if routed is not None:
                return routed
            routed = handle_app_references_api(
                self.state,
                environ,
                start_response,
                context=context,
                start_path=self.start_path,
            )
            if routed is not None:
                return routed
            routed = handle_widget_api(self.state, environ, start_response, start_path=self.start_path, workspace_id=workspace_id)
            if routed is not None:
                return routed

            if path == "/health":
                return json_response(start_response, {"status": "ok", "service": "maverick-core"})
            if path == "/favicon.ico":
                start_response("204 No Content", [("Content-Length", "0")])
                return [b""]
            if path == "/api/status":
                if context is None:
                    return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
                return json_response(
                    start_response,
                    {
                        "status": "ok",
                        "workspace_id": workspace_id,
                        "apps": enabled_app_items(self.state, workspace_id=workspace_id, start_path=self.start_path, user=user),
                    },
                )
            if path == "/api/apps":
                if context is None:
                    return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
                return json_response(
                    start_response,
                    {"items": enabled_app_items(self.state, workspace_id=workspace_id, start_path=self.start_path, user=user)},
                )
            if path in _ROOT_SHELL_STATIC_ASSETS:
                return handle_root_shell_static_asset(
                    self.state,
                    workspace_id=workspace_id,
                    root_shell_app_id=self.state.root_shell_app_id,
                    subpath=_ROOT_SHELL_STATIC_ASSETS[path],
                    start_path=self.start_path,
                    start_response=start_response,
                )
            if path == "/" or path == "/app" or path.startswith("/app/"):
                return handle_root_shell(
                    self.state,
                    workspace_id=workspace_id,
                    root_shell_app_id=self.state.root_shell_app_id,
                    start_path=self.start_path,
                    start_response=start_response,
                )
            if path.startswith("/apps/"):
                app_path = path.removeprefix("/apps/")
                app_id, _, subpath = app_path.partition("/")
                public_static_asset = is_public_app_static_asset(subpath)
                allow_unauthenticated_frontend = app_id == self.state.root_shell_app_id
                if context is None and not public_static_asset and not allow_unauthenticated_frontend:
                    return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
                return handle_app_frontend(
                    self.state,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    subpath=subpath,
                    user=user,
                    public_static_asset=public_static_asset,
                    allow_unauthenticated_frontend=allow_unauthenticated_frontend,
                    start_path=self.start_path,
                    start_response=start_response,
                )
            if path.startswith("/api/apps/") and path.endswith("/frontend/build") and method == "POST":
                if context is None:
                    return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
                app_id = path.removeprefix("/api/apps/").removesuffix("/frontend/build").strip("/")
                return handle_app_frontend_build(
                    self.state,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    user=user,
                    start_path=self.start_path,
                    start_response=start_response,
                )
            if path.startswith("/api/apps/") and path.endswith("/backend") and method == "POST":
                if context is None:
                    return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
                app_id = path.removeprefix("/api/apps/").removesuffix("/backend").strip("/")
                return handle_app_backend(
                    self.state,
                    environ=environ,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    user=user,
                    start_path=self.start_path,
                    start_response=start_response,
                    shutdown_controller=self.shutdown_controller,
                )
            if path.startswith("/api/apps/") and path.endswith("/media") and method in {"GET", "HEAD"}:
                if context is None:
                    return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
                app_id = path.removeprefix("/api/apps/").removesuffix("/media").strip("/")
                return handle_app_backend(
                    self.state,
                    environ=environ,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    user=user,
                    start_path=self.start_path,
                    start_response=start_response,
                    shutdown_controller=self.shutdown_controller,
                )
            return text_response(start_response, "Not found", status="404 Not Found")
        except HttpRequestError as error:
            return json_response(start_response, {"error": error.error}, status=error.status)
        except Exception:
            logger.exception("Unhandled platform host failure while serving `%s`.", path)
            return json_response(start_response, {"error": "internal_server_error"}, status="500 Internal Server Error")
