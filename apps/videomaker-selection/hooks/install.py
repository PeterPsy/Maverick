"""Idempotently initialize the app-owned SQLite database."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from schema import SCHEMA_VERSION, initialize_database


payload = read_entrypoint_payload()
path = initialize_database(Path(payload.data_root))
emit_json({"ok": True, "schema_version": SCHEMA_VERSION, "database": path.name})
