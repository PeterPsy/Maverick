"""Migration hook for the agents app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from seeds import seed_defaults


payload = json.loads(sys.stdin.read() or "{}")
seed_defaults(Path(payload["data_root"]))
