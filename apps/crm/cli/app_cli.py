"""CLI entrypoint for the CRM app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from errors import CrmError, error_payload
from service import app_events_for_action, handle_action


payload = read_entrypoint_payload()
arguments = payload.arguments
action = str(arguments.get("subcommand") or arguments.get("action") or "operations.manifest")
try:
    status_code, result = handle_action(payload.data_root, action, arguments)
except CrmError as error:
    status_code, result = error.status_code, error_payload(error)

response = {"status_code": status_code, "app_id": "crm", "workspace_id": payload.workspace_id, **result}
if status_code < 400:
    response["app_events"] = app_events_for_action(action)
emit_json(response)
