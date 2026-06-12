"""Mounted backend entrypoint for the CRM app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from errors import CrmError, error_payload
from service import app_events_for_action, handle_action


payload = read_entrypoint_payload()
body = dict(payload.body)
body["_app_dependencies"] = payload.raw.get("app_dependencies", {})
body["_workspace_apps"] = payload.raw.get("workspace_apps", {})
body["_workspace_id"] = payload.workspace_id
body["_app_id"] = payload.app_id
action = str(body.get("action") or "bootstrap")
try:
    status_code, result = handle_action(payload.data_root, action, body)
except CrmError as error:
    status_code, result = error.status_code, error_payload(error)
except Exception as error:  # pragma: no cover - final mount boundary guard
    status_code = 500
    result = {
        "ok": False,
        "error": "internal_error",
        "message": "Unexpected CRM backend error.",
        "details": {"type": error.__class__.__name__},
    }

response = backend_response(status_code, result)
if status_code < 400:
    response["app_events"] = app_events_for_action(action)
emit_json(response)
