"""Mounted backend entrypoint for Fitness Coach."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import app_events_for_action, error_payload, FitnessCoachError, handle_action


payload = read_entrypoint_payload()
action = str(payload.body.get("action") or "status")
arguments = dict(payload.body)
arguments["_app_dependencies"] = payload.raw.get("app_dependencies", {})
arguments["_workspace_id"] = payload.workspace_id
arguments["_app_id"] = payload.app_id

try:
    status_code, result = handle_action(payload.data_root, action, arguments)
except FitnessCoachError as error:
    status_code, result = error.status_code, error_payload(error)

response = backend_response(status_code, result)
if status_code < 400:
    events = app_events_for_action(action)
    if events:
        response["app_events"] = events
emit_json(response)
