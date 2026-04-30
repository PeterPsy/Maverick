"""Mounted backend entrypoint for Docs Studio."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import create_page, state_payload, status_payload, update_page, update_site


payload = read_entrypoint_payload()
action = str(payload.body.get("action") or "status")
try:
    if action == "status":
        response = status_payload(payload)
    elif action == "get-state":
        response = state_payload(payload)
    elif action == "update-site":
        response = {"state": update_site(payload, payload.body)}
    elif action == "create-page":
        response = create_page(payload, payload.body)
    elif action == "update-page":
        response = update_page(payload, payload.body)
    else:
        emit_json(backend_response(400, {"error": f"Unsupported action `{action}`."}))
        raise SystemExit(0)
    app_events = []
    if action in {"update-site", "create-page", "update-page"}:
        app_events.append({
            "type": "maverick.app.data-changed",
            "owner_app_id": "docs-studio",
            "resource": "state",
        })
    emit_json(backend_response(200, {"ok": True, **response, "app_events": app_events}))
except ValueError as exc:
    emit_json(backend_response(400, {"ok": False, "error": str(exc)}))
