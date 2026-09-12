"""Verify app-owned database health without mutating other workspace state."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from candidate_queries import candidate_stats
from schema import SCHEMA_VERSION, connect, database_path


payload = read_entrypoint_payload()
data_root = Path(payload.data_root)
with connect(data_root) as connection:
    actual = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
    if actual is None or actual[0] != SCHEMA_VERSION:
        raise SystemExit("schema version mismatch")
    integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
    if integrity != "ok":
        raise SystemExit(f"database integrity check failed: {integrity}")
    stats = candidate_stats(connection)
emit_json({"ok": True, "schema_version": SCHEMA_VERSION, "database": database_path(data_root).name, "stats": stats})
