"""Migration hook for the Skills app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from seeds import seed_default_skills
from store import list_skills


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
repository_root = Path(__file__).resolve().parents[3]
seed_default_skills(data_root, repository_root=repository_root)
list_skills(data_root)
