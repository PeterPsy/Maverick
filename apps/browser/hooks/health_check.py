"""Health check hook for the Browser app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from store import load_state


payload = json.loads(sys.stdin.read() or "{}")
state = load_state(str(Path(payload["data_root"])))
print(
    json.dumps(
        {
            "status": "ok",
            "schema_version": state["schema_version"],
            "broker_status": state["broker"].get("status"),
        },
        ensure_ascii=True,
    )
)
