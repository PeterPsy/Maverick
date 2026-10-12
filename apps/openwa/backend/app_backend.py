"""Mounted backend entrypoint for `openwa`."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import handle, event
from gateway import GatewayError


payload = read_entrypoint_payload()
try:
    result = handle(payload)
    response = backend_response(200, {k: v for k, v in result.items() if k not in {"platform_secret_writes", "app_events"}})
    for key in ("platform_secret_writes", "app_events"):
        if key in result:
            response[key] = result[key]
except GatewayError as error:
    response = backend_response(error.status, {"error": error.code, "detail": str(error)})
    if payload.body.get("action") in {"messages.send", "messages.reply"}:
        response["app_events"] = [event("notifications")]
emit_json(response)
