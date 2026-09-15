"""Health check hook for the Agents app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from store import list_agent_definitions


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
print(json.dumps({"status": "ok", "agent_count": len(list_agent_definitions(data_root))}))
