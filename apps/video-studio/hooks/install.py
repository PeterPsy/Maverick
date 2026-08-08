"""Idempotent install hook for SDK-generated data apps."""

from __future__ import annotations

from core.app_sdk.runtime import emit_json, read_entrypoint_payload
from core.app_sdk.storage import ensure_json_state


payload = read_entrypoint_payload()
ensure_json_state(payload.data_root, "state.json", {"schema_version": "1", "items": []})
emit_json({"ok": True})
