"""Mounted backend entrypoint for the Calendar app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import app_events_for_action, handle_action


payload = read_entrypoint_payload()
local_app_id = payload.app_id or "calendar"
action = str(payload.body.get("action") or "list")
try:
    status_code, result = handle_action(Path(payload.data_root), payload.body, app_id=local_app_id)
except ValueError as error:
    detail = str(error)
    status_code = 404 if " was not found." in detail else 400
    result = {"error": "validation_error" if status_code == 400 else "not_found", "detail": detail}
response = backend_response(status_code, result)
if status_code < 400 and not result.get("idempotent_replay"):
    response["app_events"] = app_events_for_action(action, app_id=local_app_id)
emit_json(response)
