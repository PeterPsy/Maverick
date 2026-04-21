"""Maverick Monitor app service layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from errors import MonitorValidationError
from snapshot import collect_snapshot
from store import load_state, save_state, seed_state


def handle_action(*, workspace_root: Path, data_root: Path, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "snapshot")
    if action == "snapshot":
        seed_state(data_root)
        return 200, {"state": load_state(data_root), "snapshot": collect_snapshot(workspace_root=workspace_root, data_root=data_root)}
    if action == "settings.update":
        return 200, {"state": save_state(data_root, body)}
    if action == "health.check":
        seed_state(data_root)
        return 200, {"status": "ok", "state": load_state(data_root)}
    raise MonitorValidationError(f"Unsupported monitor action: {action}")
