"""Health check hook for the Skills app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from store import list_skills


payload = json.loads(sys.stdin.read() or "{}")
result = {"status": "ok", "skill_count": len(list_skills(Path(payload["data_root"])))}
print(json.dumps(result))
