"""Health check hook for the Browser app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from broker_client import broker_health
from store import load_state


payload = json.loads(sys.stdin.read() or "{}")
state = load_state(str(Path(payload["data_root"])))
broker = broker_health(connect=True)
broker_ready = broker.get("status") == "ready" and broker.get("connected") is True
result = {
    "status": "ok" if broker_ready else "degraded",
    "schema_version": state["schema_version"],
    "broker": broker,
}
if not broker_ready:
    result["detail"] = "Browser P0 requires the broker token and a reachable Playwright run-server."
print(json.dumps(result, ensure_ascii=True))
if not broker_ready:
    sys.exit(1)
