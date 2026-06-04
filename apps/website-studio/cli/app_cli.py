"""CLI entrypoint for this entity app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, handle_action


payload = read_entrypoint_payload()
arguments = dict(payload.arguments)
arguments.setdefault("action", "sites_list")
arguments["_app_secrets"] = dict(payload.raw.get("app_secrets") or {})
arguments["_app_secret_errors"] = list(payload.raw.get("app_secret_errors") or [])
status_code, result = handle_action(Path(payload.data_root), arguments)
result["status_code"] = status_code
if status_code < 400:
    result["app_events"] = app_events_for_action(str(arguments.get("action") or "sites_list"))
emit_json(result)
