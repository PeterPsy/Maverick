"""Mounted backend entrypoint for this entity app."""

from __future__ import annotations

from pathlib import Path
import sys

for parent in Path(__file__).resolve().parents:
    if (parent / "core").is_dir():
        sys.path.insert(0, str(parent))
        break

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import app_events_for_action, handle_action


payload = read_entrypoint_payload()
body = dict(payload.body)
body["_app_secrets"] = payload.raw.get("app_secrets", {})
body["_workspace_id"] = payload.workspace_id
body["_app_id"] = payload.app_id
body["_generated_storage_root"] = payload.raw.get("generated_storage_root", "")
action = str(body.get("action") or "list")
status_code, result = handle_action(Path(payload.data_root), body)
secret_writes = result.pop("platform_secret_writes", [])
response = backend_response(status_code, result)
if secret_writes:
    response["platform_secret_writes"] = secret_writes
if status_code < 400:
    response["app_events"] = app_events_for_action(action, result)
emit_json(response)
