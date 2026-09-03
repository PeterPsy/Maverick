"""Authenticated Maverick App Store API surface."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.api.app_store_local_projects import _local_apps_payload
from core.api.app_store_mutations import handle_app_store_mutation
from core.api.app_store_payloads import _installation_payload, _server_apps_payload
from core.api.app_store_requests import _catalog_base_url
from core.api.app_store_visibility import _filter_catalog_for_context, _user_workspace_ids
from core.api.http import StartResponse, json_response, status_line
from core.api.http_validators import format_etag, if_none_match_matches
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, require_session
from core.apps.remote_store import fetch_remote_catalog



def handle_app_store_api(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
    *,
    start_path: Path,
) -> list[bytes] | None:
    """Handle authenticated app-store routes, returning None when not owned here."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if path not in {
        "/api/app-store/apps",
        "/api/app-store/install",
        "/api/app-store/install-server",
        "/api/app-store/install-local",
        "/api/app-store/installations",
        "/api/app-store/server-apps",
        "/api/app-store/register-local",
        "/api/app-store/promote-local",
        "/api/app-store/delete-local",
        "/api/app-store/uninstall",
    }:
        return None

    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response

    if path == "/api/app-store/apps" and method == "GET":
        try:
            catalog = fetch_remote_catalog(_catalog_base_url())
        except Exception as error:
            return json_response(
                start_response,
                {"error": "catalog_unavailable", "detail": str(error)},
                status=status_line(500),
            )
        payload = _filter_catalog_for_context(state, catalog, context)
        revision = hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        response_payload = {
            **payload,
            "schema": "maverick.app-store-catalog.v1",
            "revision": revision,
        }
        etag = format_etag(revision)
        response_headers = [("ETag", etag), ("Cache-Control", "private, no-cache"), ("Vary", "Cookie")]
        if if_none_match_matches(str(environ.get("HTTP_IF_NONE_MATCH") or ""), etag):
            start_response("304 Not Modified", [*response_headers, ("Content-Length", "0")])
            return []
        return json_response(start_response, response_payload, headers=response_headers)

    if path == "/api/app-store/server-apps" and method == "GET":
        return json_response(start_response, _server_apps_payload(state, context))

    if path == "/api/app-store/installations" and method == "GET":
        workspace_ids = _user_workspace_ids(state, context)
        payload = _installation_payload(state, context, workspace_ids)
        payload["local_apps"] = _local_apps_payload(state, context, workspace_ids, start_path=start_path)
        return json_response(start_response, payload)

    if method == "POST":
        mutation_response = handle_app_store_mutation(
            state,
            context,
            environ,
            start_response,
            path=path,
            start_path=start_path,
        )
        if mutation_response is not None:
            return mutation_response

    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
