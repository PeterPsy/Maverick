"""Periodic background hook for Senses."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from database import ensure_schema, require_workspace_id
from service import app_events_for_action, background_tick, dependency_resolution_payload


payload = read_entrypoint_payload()
workspace_id = require_workspace_id(payload.workspace_id)
data_root = Path(payload.data_root)
ensure_schema(data_root, workspace_id)
body = dict(payload.body)
body["_app_surface"] = payload.raw.get("surface")
dependencies = dependency_resolution_payload(payload.raw.get("app_dependencies"))
status_code, result = background_tick(data_root, workspace_id, dependencies, body)
if status_code < 400 and result.get("transcription_requests"):
    result["app_events"] = app_events_for_action("background.tick")
emit_json(result)
