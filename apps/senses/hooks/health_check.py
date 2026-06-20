"""Health check hook for Senses."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from database import ensure_schema, health_payload


payload = read_entrypoint_payload()
workspace_id = str(payload.workspace_id or "default")
data_root = Path(payload.data_root)
ensure_schema(data_root, workspace_id)
emit_json({"ok": True, **health_payload(data_root, workspace_id)})
