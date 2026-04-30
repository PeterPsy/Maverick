"""Mutation dispatch for the authenticated App Store API."""

from __future__ import annotations

from pathlib import Path

from core.api.app_store_installations import install_local, install_remote, install_server
from core.api.app_store_local_mutations import delete_local, promote_local, register_local, uninstall
from core.api.http import StartResponse
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession


def handle_app_store_mutation(
    state: PlatformState,
    context: RequestSession,
    environ: dict,
    start_response: StartResponse,
    *,
    path: str,
    start_path: Path,
) -> list[bytes] | None:
    if path == "/api/app-store/install":
        return install_remote(state, context, environ, start_response, start_path=start_path)
    if path == "/api/app-store/install-server":
        return install_server(state, context, environ, start_response, start_path=start_path)
    if path == "/api/app-store/install-local":
        return install_local(state, context, environ, start_response, start_path=start_path)
    if path == "/api/app-store/register-local":
        return register_local(state, context, environ, start_response, start_path=start_path)
    if path == "/api/app-store/promote-local":
        return promote_local(state, context, environ, start_response, start_path=start_path)
    if path == "/api/app-store/delete-local":
        return delete_local(state, context, environ, start_response, start_path=start_path)
    if path == "/api/app-store/uninstall":
        return uninstall(state, context, environ, start_response)
    return None
