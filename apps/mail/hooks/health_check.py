"""Idempotent health_check hook for this entity app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from database import health_payload


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
health = health_payload(data_root, initialize=False)
print(json.dumps({"ok": health.get("health_status") == "healthy", **health}, ensure_ascii=True))
