"""Mounted backend entrypoint for this entity app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import app_events_for_action, handle_action


payload = read_entrypoint_payload()
action = str(payload.body.get("action") or "sites_list")
body = {
    **payload.body,
    "_app_secrets": dict(payload.raw.get("app_secrets") or {}),
    "_app_secret_errors": list(payload.raw.get("app_secret_errors") or []),
}
status_code, result = handle_action(Path(payload.data_root), body)
response = backend_response(status_code, result)
if status_code < 400:
    response["app_events"] = app_events_for_action(action)
emit_json(response)
