"""CLI entrypoint for Fitness Coach."""

from __future__ import annotations

from pathlib import Path
import json
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, error_payload, FitnessCoachError, handle_action


payload = read_entrypoint_payload()
arguments = dict(payload.arguments)
payload_json = str(arguments.pop("payload_json", "") or "").strip()
if payload_json:
    try:
        parsed_payload = json.loads(payload_json)
    except json.JSONDecodeError as error:
        parsed_payload = {"action": "invalid", "_payload_json_error": str(error)}
    if isinstance(parsed_payload, dict):
        parsed_payload.update(arguments)
        arguments = parsed_payload
    else:
        arguments = {"action": "invalid", "_payload_json_error": "payload_json must decode to an object."}
arguments["_app_dependencies"] = payload.raw.get("app_dependencies", {})
arguments["_workspace_id"] = payload.workspace_id
arguments["_app_id"] = payload.app_id
action = str(arguments.get("subcommand") or arguments.get("action") or "operations.manifest")

try:
    status_code, result = handle_action(payload.data_root, action, arguments)
except FitnessCoachError as error:
    status_code, result = error.status_code, error_payload(error)

response = {"status_code": status_code, "app_id": "fitness-coach", "workspace_id": payload.workspace_id, **result}
if status_code < 400:
    events = app_events_for_action(action)
    if events:
        response["app_events"] = events
emit_json(response)
