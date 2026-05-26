"""Idempotent install hook for this entity app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from database import ensure_schema, health_payload


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
ensure_schema(data_root)
print(json.dumps({"ok": True, **health_payload(data_root)}, ensure_ascii=True))
