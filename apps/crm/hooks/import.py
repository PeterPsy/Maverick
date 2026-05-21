"""Import hook for CRM workspace data."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import handle_action
from store import initialize


payload = read_entrypoint_payload()
initialize(payload.data_root)
body = payload.body.get("payload") if isinstance(payload.body.get("payload"), dict) else payload.body
_, result = handle_action(payload.data_root, "crm.import_commit", body)
emit_json(result)
