"""Export hook for CRM workspace data."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import handle_action


payload = read_entrypoint_payload()
_, result = handle_action(payload.data_root, "crm.export", {})
emit_json(result)
