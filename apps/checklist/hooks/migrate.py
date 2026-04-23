"""Idempotent migrate hook for the Checklist app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from store import load_state, save_state


payload = read_entrypoint_payload()
data_root = Path(payload.data_root)
state = load_state(data_root)
save_state(data_root, state)
emit_json({"ok": True, "schema_version": state["schema_version"]})
