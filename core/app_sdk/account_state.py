"""Coordinate app-owned migrations into personal account data roots."""

import fcntl
import os
from pathlib import Path

from core.app_sdk.storage import read_json_state, write_json_state


def migrate_account_state(payload, migrate, *, migrate_workspace=None):
    """Import each trusted source once; apps own its schema and merge behavior."""
    root = Path(payload["data_root"])
    workspace_source = payload.get("workspace_data_root") if migrate_workspace else None
    if workspace_source:
        source = _workspace_source(workspace_source, root)
    root.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(root / ".platform-account-migration.lock", os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = read_json_state(root, ".platform-account-migrations.json", {"imported": []})
        imported = set(marker["imported"])
        if migrate_workspace and workspace_source and not marker.get("workspace_imported"):
            migrate_workspace(source, root)
            marker["workspace_imported"] = True
            write_json_state(root, ".platform-account-migrations.json", marker)
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
            marker["imported"] = sorted(imported)
            write_json_state(root, ".platform-account-migrations.json", marker)


def _workspace_source(value, root):
    source = Path(value)
    if (len(root.parents) < 3 or root.parents[2] != source
            or root.parent.parent.name != "connected-accounts" or root.name != "shared"):
        raise ValueError("Invalid workspace account migration source.")
    current = source
    for part in ("", *root.relative_to(source).parts):
        current = current / part
        if current.is_symlink():
            raise ValueError("Workspace account migration roots may not contain symlinks.")
    return source
