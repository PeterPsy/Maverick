"""Mounted backend entrypoint for `video-studio`."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import status_payload


payload = read_entrypoint_payload()
action = str(payload.body.get("action") or "status")
if action == "status":
    emit_json(backend_response(200, status_payload(payload)))
else:
    emit_json(backend_response(400, {"error": f"Unsupported action `{action}`."}))
