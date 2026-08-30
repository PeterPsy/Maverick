"""Durable intent journal for every directory rename in official update cutover."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from native_cutover_files import atomic_write_json, fsync_directory
from official_update_state import OfficialUpdateError, UPDATE_ID_PATTERN, utc_now


JOURNAL_FILE = "official-update-cutover-journal.json"
STEPS = {
    "retire_native_intent",
    "native_retired",
    "activate_candidate_intent",
    "candidate_activated",
    "rollback_retire_candidate_intent",
    "candidate_retired",
    "rollback_restore_previous_intent",
    "previous_restored",
}
FIELDS = {
    "schema_version",
    "kind",
    "update_id",
    "step",
    "created_at",
    "updated_at",
}


def write_update_journal(
    app_data_root: Path, *, update_id: str, step: str
) -> dict[str, Any]:
    if not UPDATE_ID_PATTERN.fullmatch(update_id) or step not in STEPS:
        raise OfficialUpdateError("official update cutover journal identity is invalid")
    existing = read_update_journal(app_data_root)
    if existing is not None and existing["update_id"] != update_id:
        raise OfficialUpdateError("another official update owns the cutover journal")
    now = utc_now()
    payload = {
        "schema_version": "1",
        "kind": "design-studio-official-update-cutover-journal",
        "update_id": update_id,
        "step": step,
        "created_at": existing["created_at"] if existing is not None else now,
        "updated_at": now,
    }
    atomic_write_json(Path(app_data_root) / JOURNAL_FILE, payload)
    return payload


def read_update_journal(app_data_root: Path) -> dict[str, Any] | None:
    path = Path(app_data_root) / JOURNAL_FILE
    if not path.exists() and not path.is_symlink():
        return None
    try:
        if path.is_symlink() or not path.is_file():
            raise OfficialUpdateError("official update cutover journal is unsafe")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OfficialUpdateError("official update cutover journal is unreadable") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != FIELDS
        or payload.get("schema_version") != "1"
        or payload.get("kind") != "design-studio-official-update-cutover-journal"
        or not isinstance(payload.get("update_id"), str)
        or not UPDATE_ID_PATTERN.fullmatch(payload["update_id"])
        or payload.get("step") not in STEPS
        or any(
            not isinstance(payload.get(field), str) or not payload[field]
            for field in ("created_at", "updated_at")
        )
    ):
        raise OfficialUpdateError("official update cutover journal schema is invalid")
    return payload


def clear_update_journal(app_data_root: Path, *, update_id: str) -> None:
    existing = read_update_journal(app_data_root)
    if existing is None:
        return
    if existing["update_id"] != update_id:
        raise OfficialUpdateError("official update cutover journal identity mismatch")
    path = Path(app_data_root) / JOURNAL_FILE
    path.unlink()
    fsync_directory(path.parent)


__all__ = [
    "JOURNAL_FILE",
    "clear_update_journal",
    "read_update_journal",
    "write_update_journal",
]
