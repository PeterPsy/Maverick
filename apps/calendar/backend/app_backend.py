"""Mounted backend entrypoint for the Calendar app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import app_events_for_action, handle_action, secret_lookup_for_remote_mutation


payload = read_entrypoint_payload()
if payload.raw.get("surface") == "secret_selector":
    selector = secret_lookup_for_remote_mutation(Path(payload.data_root), payload.body)
    if selector.get("requires_secrets"):
        selector["secret_requests"] = [
            {"logical_names": ["google-oauth-client-id", "google-oauth-client-secret"]},
            {"logical_names": ["google-calendar-refresh-token"], "resource_type": "calendar_connection", "resource_id": selector["resource_id"]},
        ]
    emit_json(selector)
    raise SystemExit(0)
local_app_id = payload.app_id or "calendar"
action = str(payload.body.get("action") or "list")
try:
    status_code, result = handle_action(
        Path(payload.data_root),
        payload.body,
        app_id=local_app_id,
        workspace_id=payload.workspace_id,
        app_secrets=dict(payload.raw.get("app_secrets") or {}),
        app_secret_errors=list(payload.raw.get("app_secret_errors") or []),
        allow_platform_secret_writes=True,
    )
except ValueError as error:
    detail = str(error)
    status_code = 404 if " was not found." in detail else 400
    result = {"error": "validation_error" if status_code == 400 else "not_found", "detail": detail}
platform_secret_writes = result.pop("platform_secret_writes", None)
response = backend_response(status_code, result)
if platform_secret_writes is not None:
    response["platform_secret_writes"] = platform_secret_writes
if status_code < 400 and not result.get("idempotent_replay"):
    response["app_events"] = app_events_for_action(action, app_id=local_app_id)
emit_json(response)
