"""Install hook for the Skills app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from store import ensure_data_root


payload = json.loads(sys.stdin.read() or "{}")
ensure_data_root(Path(payload["data_root"]))
