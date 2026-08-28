"""Redaction-safe transaction state for native official OpenDesign updates."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from native_cutover_files import atomic_write_json, real_directory


UPDATE_FILE = "official-update.json"
UPDATE_BACKUPS = "opendesign-update-backups"
UPDATE_ID_PATTERN = re.compile(r"^update_[A-Za-z0-9._-]{1,120}$")
PHASES = {"prepared", "activating", "committed", "rolled_back", "recovery_required"}
FIELDS = {
    "schema_version",
    "kind",
    "update_id",
    "phase",
    "created_at",
    "updated_at",
    "backup_directory",
    "previous_release",
    "candidate_release",
    "baseline_inventory",
    "migrated_inventory",
    "native_ready",
    "rolled_back",
    "bridges",
    "semantic_content_retained",
    "private_database_read",
}


class OfficialUpdateError(RuntimeError):
    """An official update could not safely complete or recover."""


def new_update_id() -> str:
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"update_{stamp}_{uuid4().hex[:8]}"


def write_update_state(app_data_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    root = real_directory(app_data_root, label="Design Studio data root")
    normalized = dict(payload)
    normalized.setdefault("schema_version", "1")
    normalized.setdefault("kind", "design-studio-official-native-update")
    normalized.setdefault("updated_at", utc_now())
    _validate(normalized)
    atomic_write_json(root / UPDATE_FILE, normalized)
    return normalized


def read_update_state(app_data_root: Path) -> dict[str, Any] | None:
    root = real_directory(app_data_root, label="Design Studio data root")
    path = root / UPDATE_FILE
    if not path.exists() and not path.is_symlink():
        return None
    try:
        if path.is_symlink() or not path.is_file():
            raise OfficialUpdateError("official update marker is unsafe")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OfficialUpdateError("official update marker is unreadable") from error
    _validate(payload)
    return payload


def release_identity(release: Any) -> dict[str, str]:
    return {
        "version": str(release.version),
        "manifest_digest": str(release.manifest_digest),
    }


def inventory_categories(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    categories = inventory.get("categories")
    if not isinstance(categories, dict):
        raise OfficialUpdateError("official update inventory categories are missing")
    normalized: dict[str, dict[str, Any]] = {}
    for name, value in categories.items():
        if (
            not isinstance(name, str)
            or not isinstance(value, dict)
            or set(value) != {"count", "sha256"}
            or isinstance(value.get("count"), bool)
            or not isinstance(value.get("count"), int)
            or value["count"] < 0
            or not _sha256(value.get("sha256"))
        ):
            raise OfficialUpdateError("official update inventory category is invalid")
        normalized[name] = {"count": value["count"], "sha256": value["sha256"]}
    if not normalized:
        raise OfficialUpdateError("official update inventory is empty")
    return normalized


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _validate(payload: object) -> None:
    if (
        not isinstance(payload, dict)
        or set(payload) != FIELDS
        or payload.get("schema_version") != "1"
        or payload.get("kind") != "design-studio-official-native-update"
        or payload.get("phase") not in PHASES
        or not isinstance(payload.get("update_id"), str)
        or not UPDATE_ID_PATTERN.fullmatch(payload["update_id"])
        or payload.get("backup_directory") != f"{UPDATE_BACKUPS}/official-update-{payload['update_id']}"
        or payload.get("semantic_content_retained") is not False
        or payload.get("private_database_read") is not False
        or not isinstance(payload.get("native_ready"), bool)
        or not isinstance(payload.get("rolled_back"), bool)
    ):
        raise OfficialUpdateError("official update marker schema is invalid")
    for key in ("created_at", "updated_at"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            raise OfficialUpdateError("official update marker timestamp is invalid")
    for key in ("previous_release", "candidate_release"):
        identity = payload.get(key)
        if (
            not isinstance(identity, dict)
            or set(identity) != {"version", "manifest_digest"}
            or not isinstance(identity.get("version"), str)
            or not _sha256(identity.get("manifest_digest"))
        ):
            raise OfficialUpdateError("official update release identity is invalid")
    for key in ("baseline_inventory", "migrated_inventory"):
        inventory_categories({"categories": payload.get(key)})
    bridges = payload.get("bridges")
    if not isinstance(bridges, dict) or set(bridges) != {"model_access", "delegation"}:
        raise OfficialUpdateError("official update bridge result is invalid")
    for value in bridges.values():
        if not isinstance(value, dict) or value.get("state") not in {"ready", "degraded", "disabled", "unchecked"}:
            raise OfficialUpdateError("official update bridge result is invalid")


def _sha256(value: object) -> bool:
    text = str(value or "")
    body = text.removeprefix("sha256:")
    return len(body) == 64 and all(character in "0123456789abcdef" for character in body)


__all__ = [
    "OfficialUpdateError",
    "UPDATE_BACKUPS",
    "UPDATE_FILE",
    "inventory_categories",
    "new_update_id",
    "read_update_state",
    "release_identity",
    "utc_now",
    "write_update_state",
]
