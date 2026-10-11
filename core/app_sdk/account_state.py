"""Coordinate app-owned migration from individual personal account data roots."""

import fcntl
import os
from pathlib import Path

from core.app_sdk.storage import read_json_state, write_json_state


def migrate_account_state(payload, migrate):
    """Import each trusted source once; apps own its schema and merge behavior."""
    root = Path(payload["data_root"])
    root.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(root / ".platform-account-migration.lock", os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = read_json_state(root, ".platform-account-migrations.json", {"imported": []})
        imported = set(marker["imported"])
        for account in payload.get("external_accounts", []):
            previous = account.get("previous_data_root")
            if not previous or account["account_id"] in imported:
                continue
            source = Path(previous)
            if source.parent != root.parent or source.name != account["account_id"] or source.is_symlink():
                raise ValueError("Invalid personal account migration source.")
            if source.is_dir():
                migrate(source, root)
            imported.add(account["account_id"])
            write_json_state(root, ".platform-account-migrations.json", {"imported": sorted(imported)})
