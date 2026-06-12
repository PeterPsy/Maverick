"""Idempotent migrate hook for Fitness Coach."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import ensure_state


payload = read_entrypoint_payload()
ensure_state(payload.data_root)
emit_json({"ok": True})
