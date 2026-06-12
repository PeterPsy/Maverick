"""CLI entrypoint for this entity app."""

from __future__ import annotations

from pathlib import Path
import sys

for parent in Path(__file__).resolve().parents:
    if (parent / "core").is_dir():
        sys.path.insert(0, str(parent))
        break

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, handle_action, resolve_secret_resource, resolve_secret_resource_inventory


payload = read_entrypoint_payload()
arguments = dict(payload.arguments)
if payload.raw.get("surface") == "secret_resource_inventory":
    emit_json(resolve_secret_resource_inventory(Path(payload.data_root)))
    raise SystemExit(0)
if payload.raw.get("surface") == "secret_selector":
    arguments["_app_secret_selector"] = payload.raw.get("app_secret_selector", {})
    emit_json(resolve_secret_resource(Path(payload.data_root), arguments))
    raise SystemExit(0)
arguments["_app_secrets"] = payload.raw.get("app_secrets", {})
arguments["_generated_storage_root"] = payload.raw.get("generated_storage_root", "")
arguments["_workspace_id"] = payload.workspace_id
arguments.setdefault("action", "threads.list")
if arguments.get("action") == "references.manifest":
    arguments["action"] = "reference_manifest"
status_code, result = handle_action(Path(payload.data_root), arguments)
result["status_code"] = status_code
if status_code < 400:
    result.setdefault("app_id", payload.app_id)
    result.setdefault("workspace_id", payload.workspace_id)
    result["app_events"] = app_events_for_action(str(arguments.get("action") or "list"), result)
emit_json(result)
