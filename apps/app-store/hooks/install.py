"""Install hook for the app-store app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from store import load_state


payload = json.loads(sys.stdin.read() or "{}")
load_state(Path(payload["data_root"]))
