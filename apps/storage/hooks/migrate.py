"""Migrate hook for the Storage app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from store import seed_state
from inventory_admin import migration_action


payload = json.loads(sys.stdin.read() or "{}")
seed_state(Path(payload["data_root"]))
body = payload.get('body') or {}
if body.get('phase'):
    result = migration_action(Path(payload['data_root']), Path(payload['uploaded_storage_root']),
        Path(payload['generated_storage_root']), {**body, '_surface': 'migrate'})
    print(json.dumps(result))
