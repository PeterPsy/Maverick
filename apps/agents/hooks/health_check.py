"""Health check hook for the agents app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from store import list_agent_types, list_roles


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
result = {
    "status": "ok",
    "role_count": len(list_roles(data_root)),
    "agent_type_count": len(list_agent_types(data_root)),
}
print(json.dumps(result))
