"""Redaction-safe transaction state for native official OpenDesign updates."""

from __future__ import annotations

from collections import Counter
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
INVENTORY_CATEGORIES = (
    "projects",
    "conversations",
    "ordered_messages",
    "design_systems",
    "project_files",
    "artifacts",
    "settings",
    "run_references",
)
PARTIALLY_PROTECTED_IDENTITY_CATEGORIES = {"design_systems"}
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
    "migration_guard",
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
    if set(normalized) != set(INVENTORY_CATEGORIES):
        raise OfficialUpdateError("official update inventory categories are incomplete")
    return normalized


def migration_preservation_guard(
    baseline: dict[str, Any],
    migrated: dict[str, Any],
) -> dict[str, Any]:
    """Prove that every native identity and its redaction-safe content survive."""
    baseline_categories = inventory_categories(baseline)
    migrated_categories = inventory_categories(migrated)
    baseline_sets = _identity_sets(baseline, baseline_categories)
    migrated_sets = _identity_sets(migrated, migrated_categories)
    baseline_content = _content_sets(baseline)
    migrated_content = _content_sets(migrated)
    lost_identity_counts: dict[str, int] = {}
    added_identity_counts: dict[str, int] = {}
    lost_content_counts: dict[str, int] = {}
    added_content_counts: dict[str, int] = {}
    for category in INVENTORY_CATEGORIES:
        before = Counter(baseline_sets[category])
        after = Counter(migrated_sets[category])
        lost_identity_counts[category] = sum((before - after).values())
        added_identity_counts[category] = sum((after - before).values())
        before_content = Counter(baseline_content[category])
        after_content = Counter(migrated_content[category])
        lost_content_counts[category] = sum((before_content - after_content).values())
        added_content_counts[category] = sum((after_content - before_content).values())
    return {
        "state": (
            "failed"
            if any(lost_identity_counts.values()) or any(lost_content_counts.values())
            else "passed"
        ),
        "protected_categories": list(INVENTORY_CATEGORIES),
        "baseline_identity_counts": {
            category: len(baseline_sets[category]) for category in INVENTORY_CATEGORIES
        },
        "migrated_identity_counts": {
            category: len(migrated_sets[category]) for category in INVENTORY_CATEGORIES
        },
        "added_identity_counts": added_identity_counts,
        "lost_identity_counts": lost_identity_counts,
        "baseline_content_counts": {
            category: len(baseline_content[category]) for category in INVENTORY_CATEGORIES
        },
        "migrated_content_counts": {
            category: len(migrated_content[category]) for category in INVENTORY_CATEGORIES
        },
        "added_content_counts": added_content_counts,
        "lost_content_counts": lost_content_counts,
    }


def incomplete_migration_guard() -> dict[str, Any]:
    counts = {category: 0 for category in INVENTORY_CATEGORIES}
    return {
        "state": "not_completed",
        "protected_categories": list(INVENTORY_CATEGORIES),
        "baseline_identity_counts": dict(counts),
        "migrated_identity_counts": dict(counts),
        "added_identity_counts": dict(counts),
        "lost_identity_counts": dict(counts),
        "baseline_content_counts": dict(counts),
        "migrated_content_counts": dict(counts),
        "added_content_counts": dict(counts),
        "lost_content_counts": dict(counts),
    }


def empty_inventory_categories() -> dict[str, dict[str, Any]]:
    empty_digest = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    return {
        category: {"count": 0, "sha256": empty_digest}
        for category in INVENTORY_CATEGORIES
    }


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
    _validate_migration_guard(
        payload.get("migration_guard"),
        phase=str(payload.get("phase")),
        baseline_inventory=payload["baseline_inventory"],
        migrated_inventory=payload["migrated_inventory"],
    )
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


def _identity_sets(
    inventory: dict[str, Any],
    categories: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    raw = inventory.get("identity_sets")
    if not isinstance(raw, dict) or set(raw) != set(INVENTORY_CATEGORIES):
        raise OfficialUpdateError("official update identity inventory is missing")
    normalized: dict[str, list[str]] = {}
    for category in INVENTORY_CATEGORIES:
        values = raw.get(category)
        expected_count = categories[category]["count"]
        if (
            not isinstance(values, list)
            or not _identity_count_matches_inventory(
                category,
                protected_count=len(values),
                inventory_count=expected_count,
            )
            or any(not isinstance(value, str) or not _sha256(value) for value in values)
        ):
            raise OfficialUpdateError("official update identity inventory is invalid")
        normalized[category] = list(values)
    return normalized


def _content_sets(
    inventory: dict[str, Any],
) -> dict[str, list[str]]:
    raw = inventory.get("content_sets")
    if not isinstance(raw, dict) or set(raw) != set(INVENTORY_CATEGORIES):
        raise OfficialUpdateError("official update content inventory is missing")
    normalized: dict[str, list[str]] = {}
    for category in INVENTORY_CATEGORIES:
        values = raw.get(category)
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) or not _sha256(value) for value in values)
        ):
            raise OfficialUpdateError("official update content inventory is invalid")
        normalized[category] = list(values)
    return normalized


def _validate_migration_guard(
    value: object,
    *,
    phase: str,
    baseline_inventory: dict[str, Any],
    migrated_inventory: dict[str, Any],
) -> None:
    fields = {
        "state",
        "protected_categories",
        "baseline_identity_counts",
        "migrated_identity_counts",
        "added_identity_counts",
        "lost_identity_counts",
        "baseline_content_counts",
        "migrated_content_counts",
        "added_content_counts",
        "lost_content_counts",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise OfficialUpdateError("official update migration guard is invalid")
    state = value.get("state")
    if state not in {"passed", "failed", "not_completed"}:
        raise OfficialUpdateError("official update migration guard is invalid")
    if phase != "recovery_required" and state != "passed":
        raise OfficialUpdateError("official update migration guard did not pass")
    if value.get("protected_categories") != list(INVENTORY_CATEGORIES):
        raise OfficialUpdateError("official update migration guard is invalid")
    for key in (
        "baseline_identity_counts",
        "migrated_identity_counts",
        "added_identity_counts",
        "lost_identity_counts",
        "baseline_content_counts",
        "migrated_content_counts",
        "added_content_counts",
        "lost_content_counts",
    ):
        counts = value.get(key)
        if (
            not isinstance(counts, dict)
            or set(counts) != set(INVENTORY_CATEGORIES)
            or any(
                isinstance(count, bool) or not isinstance(count, int) or count < 0
                for count in counts.values()
            )
        ):
            raise OfficialUpdateError("official update migration guard is invalid")
    lost_identities = value["lost_identity_counts"]
    lost_content = value["lost_content_counts"]
    if state == "passed" and (any(lost_identities.values()) or any(lost_content.values())):
        raise OfficialUpdateError("official update migration guard is invalid")
    if state == "failed" and not (
        any(lost_identities.values()) or any(lost_content.values())
    ):
        raise OfficialUpdateError("official update migration guard is invalid")
    if state == "not_completed":
        if any(
            count
            for key in fields - {"state", "protected_categories"}
            for count in value[key].values()
        ):
            raise OfficialUpdateError("official update migration guard is invalid")
        return
    for category in INVENTORY_CATEGORIES:
        baseline_count = value["baseline_identity_counts"][category]
        migrated_count = value["migrated_identity_counts"][category]
        added_count = value["added_identity_counts"][category]
        lost_count = value["lost_identity_counts"][category]
        baseline_content_count = value["baseline_content_counts"][category]
        migrated_content_count = value["migrated_content_counts"][category]
        added_content_count = value["added_content_counts"][category]
        lost_content_count = value["lost_content_counts"][category]
        baseline_inventory_count = baseline_inventory[category]["count"]
        migrated_inventory_count = migrated_inventory[category]["count"]
        identity_counts_match_inventory = _identity_count_matches_inventory(
            category,
            protected_count=baseline_count,
            inventory_count=baseline_inventory_count,
        ) and _identity_count_matches_inventory(
            category,
            protected_count=migrated_count,
            inventory_count=migrated_inventory_count,
        )
        if (
            not identity_counts_match_inventory
            or baseline_count - lost_count + added_count != migrated_count
            or baseline_content_count - lost_content_count + added_content_count
            != migrated_content_count
        ):
            raise OfficialUpdateError("official update migration guard is invalid")


def _identity_count_matches_inventory(
    category: str,
    *,
    protected_count: int,
    inventory_count: int,
) -> bool:
    if category in PARTIALLY_PROTECTED_IDENTITY_CATEGORIES:
        return protected_count <= inventory_count
    return protected_count == inventory_count


__all__ = [
    "OfficialUpdateError",
    "UPDATE_BACKUPS",
    "UPDATE_FILE",
    "INVENTORY_CATEGORIES",
    "empty_inventory_categories",
    "incomplete_migration_guard",
    "inventory_categories",
    "migration_preservation_guard",
    "new_update_id",
    "read_update_state",
    "release_identity",
    "utc_now",
    "write_update_state",
]
