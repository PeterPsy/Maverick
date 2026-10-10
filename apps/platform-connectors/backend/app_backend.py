"""Mounted backend entrypoint for `platform-connectors`."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import handle


payload = read_entrypoint_payload()
status_code, result = handle(payload)
emit_json(backend_response(status_code,result))
