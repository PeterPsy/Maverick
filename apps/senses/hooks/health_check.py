"""Health check hook for Senses."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from database import ensure_schema, health_payload, require_workspace_id
from service import dependency_resolution_payload


payload = read_entrypoint_payload()
workspace_id = require_workspace_id(payload.workspace_id)
data_root = Path(payload.data_root)
ensure_schema(data_root, workspace_id)
result = {"ok": True, **health_payload(data_root, workspace_id)}
if payload.raw.get("hook_name") == "health_check":
    dependencies = dependency_resolution_payload(payload.raw.get("app_dependencies"))
    result["dependencies"] = dependencies
    if dependencies["status"] != "resolved":
        result["ok"] = False
        result["status"] = "dependency_resolution_pending"
        emit_json(result)
        raise SystemExit(1)
emit_json(result)
