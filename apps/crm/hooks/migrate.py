"""Idempotent migrate hook for the CRM app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from store import initialize


payload = read_entrypoint_payload()
initialize(payload.data_root)
emit_json({"ok": True, "schema_version": "1"})
