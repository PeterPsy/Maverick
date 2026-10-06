"""Migration hook for the Browser app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import ensure_installed_state
from lab_runtime_control import ensure_running


payload = json.loads(sys.stdin.read() or "{}")
state = ensure_installed_state(Path(payload["data_root"]))
runtime = ensure_running(enable=True)
print(json.dumps({"status": "ok", "schema_version": state["schema_version"], "lab_runtime": runtime}, ensure_ascii=True))
