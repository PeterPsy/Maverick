"""Shared request helpers for the authenticated App Store API."""

from __future__ import annotations

import os

from core.api.http import StartResponse, json_response
from core.api.session_api import RequestSession
from core.apps.contract_common import validate_app_id
from core.apps.remote_store import catalog_base_url


def _catalog_base_url() -> str:
    return catalog_base_url(os.environ.get("MAVERICK_APP_STORE_URL"))


def _safe_app_id_response(raw_app_id: str, start_response: StartResponse) -> str | list[bytes]:
    if not raw_app_id:
        return json_response(start_response, {"error": "app_id_required"}, status="400 Bad Request")
    try:
        return validate_app_id(raw_app_id)
    except ValueError:
        return json_response(start_response, {"error": "invalid_app_id"}, status="400 Bad Request")


def _workspace_ids_from_body(body: dict, context: RequestSession) -> list[str]:
    raw_workspace_ids = body.get("workspace_ids")
    if raw_workspace_ids is None:
        return [context.workspace_id]
    if not isinstance(raw_workspace_ids, list):
        return []
    return [str(workspace_id).strip() for workspace_id in raw_workspace_ids if str(workspace_id).strip()]
