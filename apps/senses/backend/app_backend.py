"""Mounted backend entrypoint for Senses."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import app_events_for_action, handle_action


payload = read_entrypoint_payload()
body = dict(payload.body)
body["_app_dependencies"] = payload.raw.get("app_dependencies", {})
body["_workspace_id"] = payload.workspace_id
body["_app_id"] = payload.app_id
body["_app_actor"] = {
    "user_id": payload.user_id,
    "workspace_role": payload.workspace_role,
    "platform_role": payload.platform_role,
    "effective_mode": payload.effective_mode,
}
action = str(body.get("action") or "manifest")
status_code, result = handle_action(Path(payload.data_root), body)
response = backend_response(status_code, result)
if status_code < 400:
    response["app_events"] = app_events_for_action(action)
emit_json(response)
