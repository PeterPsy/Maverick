"""CLI entrypoint for this entity app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, handle_action, resolve_secret_resource


payload = read_entrypoint_payload()
arguments = dict(payload.arguments)
arguments.setdefault("action", "sites_list")
if arguments.get("action") == "references.manifest":
    arguments["action"] = "reference_manifest"
if payload.raw.get("surface") == "secret_selector":
    arguments["_app_secret_selector"] = payload.raw.get("app_secret_selector", {})
    emit_json(resolve_secret_resource(Path(payload.data_root), arguments))
    raise SystemExit(0)
arguments["_app_secrets"] = dict(payload.raw.get("app_secrets") or {})
arguments["_app_secret_errors"] = list(payload.raw.get("app_secret_errors") or [])
arguments["_app_actor"] = {
    "user_id": payload.user_id,
    "workspace_role": payload.workspace_role,
    "platform_role": payload.platform_role,
    "effective_mode": payload.effective_mode,
}
status_code, result = handle_action(Path(payload.data_root), arguments)
result["status_code"] = status_code
if status_code < 400:
    result.setdefault("app_id", payload.app_id)
    result.setdefault("workspace_id", payload.workspace_id)
    result["app_events"] = app_events_for_action(str(arguments.get("action") or "sites_list"), arguments)
emit_json(result)
