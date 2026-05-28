"""Idempotent install hook for the Calendar app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload
from core.app_sdk.storage import update_json_state

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from constants import SCHEMA_VERSION
from service import default_state, normalize_state_for_storage


payload = read_entrypoint_payload()
update_json_state(payload.data_root, "state.json", normalize_state_for_storage, default_state())
emit_json({"ok": True, "schema_version": SCHEMA_VERSION})
