"""Health hook for the chat app."""

from __future__ import annotations

import json
from pathlib import Path
import sys


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
state_path = data_root / "state.json"
if not state_path.is_file():
    raise SystemExit(1)
state = json.loads(state_path.read_text(encoding="utf-8"))
if not isinstance(state.get("projects", []), list):
    raise SystemExit(1)
if not isinstance(state.get("preferences", {}), dict):
    raise SystemExit(1)
