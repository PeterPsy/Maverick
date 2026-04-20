"""Migration hook for the app-store app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from store import load_state, save_state


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
save_state(data_root, load_state(data_root))
