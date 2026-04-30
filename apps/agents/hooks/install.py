"""Install hook for the agents app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from seeds import seed_defaults


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
seed_defaults(data_root)
