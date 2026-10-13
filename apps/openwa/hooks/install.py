"""Idempotent install hook for SDK-generated data apps."""

from __future__ import annotations

from core.app_sdk.runtime import emit_json, read_entrypoint_payload
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from state import database


payload = read_entrypoint_payload()
with database(payload.data_root):
    pass
emit_json({"ok": True})
