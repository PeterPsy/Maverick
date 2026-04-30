"""Memory app health-check hook."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from store import health_payload


payload = json.loads(sys.stdin.read() or "{}")
print(json.dumps(health_payload(Path(payload["data_root"])), ensure_ascii=False))
