"""Mounted backend entrypoint for the Browser app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import app_events_for_action, handle_action


payload = read_entrypoint_payload()
local_app_id = payload.app_id or "browser"
action = str(payload.body.get("action") or "status")
status_code, result = handle_action(
    Path(payload.data_root),
    payload.body,
    app_id=local_app_id,
    workspace_id=payload.workspace_id,
    effective_mode=payload.effective_mode,
    platform_role=payload.platform_role,
    workspace_role=payload.workspace_role,
)
response = backend_response(status_code, result)
if status_code < 400:
    response["app_events"] = app_events_for_action(action)
emit_json(response)
