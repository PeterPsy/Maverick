"""Strict marker and legacy-path state for the one-time native cutover."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
import re
from typing import Any, Iterator
from uuid import uuid4

from native_cutover_files import atomic_write_json, real_directory


GENERATION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MARKER_FILE = "native-cutover.json"
BACKUP_DIRECTORY = "opendesign-cutover-backups"
BACKUP_BASE_FILES = (
    ".maverick-app.json",
    "adapter-state.json",
    "state.json",
    "delegations/state.json",
    "opendesign/control.json",
    "opendesign/legacy-project-map.json",
)
READ_ONLY_BASE_FILES = (
    "adapter-state.json",
    "state.json",
    "opendesign/control.json",
    "opendesign/legacy-project-map.json",
)
VALID_PHASES = {"prepared", "activating", "committed", "activation_failed"}
INVENTORY_CATEGORIES = {
    "projects",
    "conversations",
    "ordered_messages",
    "design_systems",
    "project_files",
    "artifacts",
    "settings",
    "run_references",
}
MARKER_FIELDS = {
    "schema_version",
    "kind",
    "cutover_id",
    "phase",
    "created_at",
    "updated_at",
    "backup_directory",
    "source_generation",
    "source_tree_sha256",
    "native_tree_sha256",
    "public_inventory_sha256",
    "inventory_categories",
    "legacy_read_only_files",
    "legacy_source_read_only",
    "legacy_writer_enabled",
    "native_writer_started",
    "native_ready",
    "rollback_to_legacy_allowed",
    "writer",
    "semantic_content_copied_to_maverick_state",
}


class NativeDataCutoverError(RuntimeError):
    """The one-time native data cutover failed before semantic activation."""


def legacy_source(app_root: Path) -> tuple[Path, str]:
    legacy_root = real_directory(app_root / "opendesign", label="legacy OpenDesign root")
    if legacy_root.parent != app_root:
        raise NativeDataCutoverError("legacy OpenDesign root escaped app data")
    try:
        control_path = legacy_root / "control.json"
        if control_path.is_symlink() or not control_path.is_file():
            raise NativeDataCutoverError("legacy OpenDesign control is unsafe")
        if control_path.resolve(strict=True).parent != legacy_root:
            raise NativeDataCutoverError("legacy OpenDesign control escaped app data")
        control = json.loads(control_path.read_text(encoding="utf-8"))
        active = control.get("active") if isinstance(control, dict) else None
        generation = active.get("data_generation") if isinstance(active, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NativeDataCutoverError("legacy OpenDesign control is unreadable") from error
    if not isinstance(generation, str) or not GENERATION_PATTERN.fullmatch(generation):
        raise NativeDataCutoverError("legacy OpenDesign active generation is invalid")
    instances = real_directory(legacy_root / "instances", label="legacy OpenDesign instances")
    generation_root = real_directory(
        instances / generation, label="legacy OpenDesign generation"
    )
    source = real_directory(generation_root / "data", label="legacy canonical OpenDesign data")
    if source.parent != generation_root or app_root not in source.parents:
        raise NativeDataCutoverError("legacy OpenDesign source escaped its generation")
    return source, generation


def backup_files(generation: str) -> tuple[str, ...]:
    return (*BACKUP_BASE_FILES, *_runtime_files(generation))


def read_only_files(generation: str) -> tuple[str, ...]:
    return (*READ_ONLY_BASE_FILES, *_runtime_files(generation))


def existing_marker(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    marker = read_marker(path)
    if marker.get("phase") not in VALID_PHASES:
        raise NativeDataCutoverError("native cutover marker phase is invalid")
    return marker


def read_marker(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise NativeDataCutoverError("native cutover marker is unsafe")
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NativeDataCutoverError("native cutover marker is unreadable") from error
    _validate_marker(marker)
    return marker


def begin_native_writer_activation(app_data_root: Path, *, cutover_id: str) -> dict[str, Any]:
    """Irreversibly close legacy rollback immediately before native startup."""
    root = real_directory(app_data_root, label="Design Studio data root")
    with cutover_lock(root / ".native-cutover.lock"):
        marker = read_marker(root / MARKER_FILE)
        _require_identity(marker, cutover_id)
        phase = marker.get("phase")
        if phase == "prepared":
            marker.update(
                {
                    "phase": "activating",
                    "native_writer_started": True,
                    "native_ready": False,
                    "rollback_to_legacy_allowed": False,
                    "legacy_writer_enabled": False,
                    "updated_at": utc_now(),
                }
            )
            atomic_write_json(root / MARKER_FILE, marker)
        elif phase not in {"activating", "committed", "activation_failed"}:
            raise NativeDataCutoverError("native cutover cannot enter activation")
        return marker


def finish_native_writer_activation(
    app_data_root: Path,
    *,
    cutover_id: str,
    ready: bool,
) -> dict[str, Any]:
    """Record readiness without ever reopening the retired legacy writer."""
    if not isinstance(ready, bool):
        raise NativeDataCutoverError("native writer readiness must be boolean")
    root = real_directory(app_data_root, label="Design Studio data root")
    with cutover_lock(root / ".native-cutover.lock"):
        marker = read_marker(root / MARKER_FILE)
        _require_identity(marker, cutover_id)
        if marker.get("phase") == "prepared" or marker.get("native_writer_started") is not True:
            raise NativeDataCutoverError("native writer activation was not begun")
        marker.update(
            {
                "phase": "committed" if ready else "activation_failed",
                "native_writer_started": True,
                "native_ready": bool(ready),
                "rollback_to_legacy_allowed": False,
                "legacy_writer_enabled": False,
                "updated_at": utc_now(),
            }
        )
        atomic_write_json(root / MARKER_FILE, marker)
        return marker


@contextmanager
def cutover_lock(path: Path) -> Iterator[None]:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def new_cutover_id() -> str:
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"native_{timestamp}_{uuid4().hex[:8]}"


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _runtime_files(generation: str) -> tuple[str, str]:
    runtime = f"opendesign/instances/{generation}/data/maverick-runtime"
    return (f"{runtime}/correlations.json", f"{runtime}/conversation-bindings.json")


def _require_identity(marker: dict[str, Any], cutover_id: str) -> None:
    if marker.get("cutover_id") != cutover_id:
        raise NativeDataCutoverError("native cutover marker identity mismatch")


def _validate_marker(marker: object) -> None:
    if (
        not isinstance(marker, dict)
        or set(marker) != MARKER_FIELDS
        or marker.get("schema_version") != "1"
        or marker.get("kind") != "design-studio-official-native-cutover"
        or marker.get("writer") != "official-native-opendesign"
        or marker.get("semantic_content_copied_to_maverick_state") is not False
        or marker.get("legacy_source_read_only") is not True
        or marker.get("legacy_writer_enabled") is not False
    ):
        raise NativeDataCutoverError("native cutover marker schema is invalid")
    cutover_id = marker.get("cutover_id")
    generation = marker.get("source_generation")
    if (
        not isinstance(cutover_id, str)
        or not GENERATION_PATTERN.fullmatch(cutover_id)
        or not isinstance(generation, str)
        or not GENERATION_PATTERN.fullmatch(generation)
        or marker.get("backup_directory")
        != f"{BACKUP_DIRECTORY}/official-native-{cutover_id}"
    ):
        raise NativeDataCutoverError("native cutover marker identity is invalid")
    for key in ("source_tree_sha256", "native_tree_sha256", "public_inventory_sha256"):
        value = marker.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise NativeDataCutoverError("native cutover marker digest is invalid")
    categories = marker.get("inventory_categories")
    if not isinstance(categories, dict) or set(categories) != INVENTORY_CATEGORIES:
        raise NativeDataCutoverError("native cutover inventory marker is invalid")
    for value in categories.values():
        if (
            not isinstance(value, dict)
            or set(value) != {"count", "sha256"}
            or isinstance(value.get("count"), bool)
            or not isinstance(value.get("count"), int)
            or value["count"] < 0
            or not isinstance(value.get("sha256"), str)
            or len(value["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in value["sha256"])
        ):
            raise NativeDataCutoverError("native cutover inventory marker is invalid")
    if not all(isinstance(marker.get(key), str) and marker[key] for key in ("created_at", "updated_at")):
        raise NativeDataCutoverError("native cutover marker timestamps are invalid")
    readonly = marker.get("legacy_read_only_files")
    if not isinstance(readonly, list) or any(not isinstance(item, str) for item in readonly):
        raise NativeDataCutoverError("native cutover legacy file marker is invalid")
    expected_phase = {
        "prepared": (False, False, True),
        "activating": (True, False, False),
        "committed": (True, True, False),
        "activation_failed": (True, False, False),
    }
    phase = marker.get("phase")
    observed = (
        marker.get("native_writer_started"),
        marker.get("native_ready"),
        marker.get("rollback_to_legacy_allowed"),
    )
    if phase not in expected_phase or observed != expected_phase[phase]:
        raise NativeDataCutoverError("native cutover marker phase is inconsistent")
