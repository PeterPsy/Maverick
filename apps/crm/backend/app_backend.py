"""Mounted backend entrypoint for the CRM app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from errors import CrmError, error_payload
from service import app_events_for_action, handle_action


payload = read_entrypoint_payload()
action = str(payload.body.get("action") or "bootstrap")
try:
    status_code, result = handle_action(payload.data_root, action, payload.body)
except CrmError as error:
    status_code, result = error.status_code, error_payload(error)

response = backend_response(status_code, result)
if status_code < 400:
    response["app_events"] = app_events_for_action(action)
emit_json(response)
