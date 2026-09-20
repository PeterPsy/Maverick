"""Install hook for the Storage app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from store import seed_state
from inventory_migration import initialize_inventory


payload = json.loads(sys.stdin.read() or "{}")
seed_state(Path(payload["data_root"]))
initialize_inventory(Path(payload['data_root']))
