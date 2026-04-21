"""Health hook for Maverick Monitor."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from store import load_state, seed_state


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
seed_state(data_root)
print(json.dumps({"status": "ok", "state": load_state(data_root)}, ensure_ascii=False))
