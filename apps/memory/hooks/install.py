"""Memory app install hook."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from store import ensure_schema, health_payload


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
ensure_schema(data_root)
print(json.dumps({"status": "ok", **health_payload(data_root)}, ensure_ascii=False))

