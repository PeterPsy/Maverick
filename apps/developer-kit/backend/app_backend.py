"""Backend entrypoint for the Developer Kit app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import handle_action


payload = read_entrypoint_payload()
status_code, result = handle_action(payload.raw, payload.body)
emit_json(backend_response(status_code, result))
