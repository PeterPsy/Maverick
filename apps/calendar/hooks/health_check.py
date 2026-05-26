"""Calendar health-check hook."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import health_payload


payload = read_entrypoint_payload()
emit_json(health_payload(Path(payload.data_root)))
