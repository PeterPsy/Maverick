"""Recover the enabled installation-local Lab worker after a backend restart."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from lab_runtime_control import ensure_running

payload = json.loads(sys.stdin.read() or "{}")
result = ensure_running()
print(json.dumps({"status": "ok", "lab_runtime": result}))
