"""Stable revision for a self-contained agent definition."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def agent_runtime_revision(agent: dict[str, Any]) -> str:
    document = {
        key: agent.get(key)
        for key in (
            "id",
            "name",
            "description",
            "instructions",
            "skill_ids",
            "enabled",
        )
    }
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"
