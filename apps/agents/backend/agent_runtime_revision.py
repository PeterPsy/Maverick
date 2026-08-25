"""Stable revision over every field used to materialize an agent runtime."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def agent_runtime_revision(
    *,
    agent_type: dict[str, Any],
    role: dict[str, Any],
    common_prompt: str,
) -> str:
    document = {
        "agent_type": {
            key: agent_type.get(key)
            for key in (
                "id",
                "name",
                "description",
                "role_id",
                "skill_ids",
                "skill_activation_mode",
                "trace_verbosity",
                "enabled",
            )
        },
        "role": {
            key: role.get(key)
            for key in ("id", "name", "description", "instructions")
        },
        "common_prompt": str(common_prompt or ""),
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"
