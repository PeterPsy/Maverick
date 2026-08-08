"""Health hook for SDK-generated data apps."""

from __future__ import annotations

from pathlib import Path

from core.app_sdk.runtime import emit_json, read_entrypoint_payload


payload = read_entrypoint_payload()
if not Path(payload.data_root).exists():
    raise SystemExit("data root does not exist")
emit_json({"ok": True})
