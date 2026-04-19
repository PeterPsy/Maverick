"""Health hook for the chat app."""

from __future__ import annotations

import json
from pathlib import Path
import sys


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
threads_path = data_root / "threads.json"
if not threads_path.is_file():
    raise SystemExit(1)
state = json.loads(threads_path.read_text(encoding="utf-8"))
if not isinstance(state.get("threads"), list):
    raise SystemExit(1)
if not isinstance(state.get("projects", []), list):
    raise SystemExit(1)
