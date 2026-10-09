"""Collect reminders even when no Calendar frontend is mounted."""

from pathlib import Path
import sys
from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from reminders import reminder_tick

payload = read_entrypoint_payload()
emit_json(reminder_tick(Path(payload.data_root)))
