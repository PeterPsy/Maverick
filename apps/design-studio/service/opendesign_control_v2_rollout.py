"""One-time, fail-closed conversion of a verified OpenDesign control v1 selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import stat
from typing import Callable, Mapping

from opendesign_generation_control import MAX_CONTROL_BYTES, write_generation_control
from opendesign_generation_model import GenerationControl, GenerationControlError, LaunchSelection


_CONTROL_V1_FIELDS = {"schema_version", "active", "previous", "migration_id", "updated_at"}
_SELECTION_V1_FIELDS = {"bundle_artifact_sha256", "od_version", "data_generation"}


class ControlV2RolloutError(RuntimeError):
    """Raised when legacy control cannot be safely converted in place."""


@dataclass(frozen=True)
class ControlV2RolloutOutcome:
    control: GenerationControl
    retired_migration_id: str | None
    converted: bool


def convert_control_v1_to_v2(
    root: Path,
    *,
    expected_runtime_artifact_sha256: str,
    web_overlay_sha256: str,
    expected_od_version: str,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    now: Callable[[], str] | None = None,
) -> ControlV2RolloutOutcome:
    """Attach the canonical overlay before the first runtime-v2 controlled copy.

    The old release retention record is deliberately retired here. The immediately
    following controlled-copy cutover writes a schema-v2 journal and retains the
    then-active runtime/data/overlay selection as ``previous_release``.
    """
    root = _real_directory(root, label="OpenDesign data root")
    ensure_control_v2_layout(root)
    payload = _read_strict_json(root / "control.json")
    if not isinstance(payload, dict) or set(payload) != _CONTROL_V1_FIELDS:
        raise ControlV2RolloutError("legacy control contains unknown or missing fields")
    if payload.get("schema_version") != "1":
        raise ControlV2RolloutError("control is not the supported legacy schema v1")
    active = _legacy_selection(payload.get("active"), label="active")
    if active[0] != expected_runtime_artifact_sha256 or active[1] != expected_od_version:
        raise ControlV2RolloutError("legacy active selection does not match the rollout source")
    retired_migration_id = payload.get("migration_id")
    previous = payload.get("previous")
    if (retired_migration_id is None) != (previous is None):
        raise ControlV2RolloutError("legacy release retention metadata is incomplete")
    if retired_migration_id is not None:
        if not isinstance(retired_migration_id, str) or not retired_migration_id.startswith("migration_"):
            raise ControlV2RolloutError("legacy migration id is invalid")
        previous_selection = _legacy_selection(previous, label="previous")
        _validate_committed_legacy_journal(
            root,
            migration_id=retired_migration_id,
            previous=previous_selection,
            active=active,
        )

    selection = LaunchSelection(
        runtime_artifact_sha256=active[0],
        web_overlay_sha256=web_overlay_sha256,
        od_version=active[1],
        data_generation=active[2],
    )
    control = GenerationControl(
        active=selection,
        previous_release=None,
        previous_web=None,
        migration_id=None,
        web_activation_id=None,
        updated_at=(now or _utc_now)(),
    )
    try:
        write_generation_control(
            root,
            control,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
    except (GenerationControlError, OSError) as exc:
        raise ControlV2RolloutError("schema-v2 control conversion failed closed") from exc
    return ControlV2RolloutOutcome(control, retired_migration_id, True)


def ensure_control_v2_layout(root: Path) -> Path:
    """Create only the schema-v2 owned journal directory, rejecting unsafe paths."""
    root = _real_directory(root, label="OpenDesign data root")
    destination = root / "web-activations"
    try:
        mode = destination.lstat().st_mode
    except FileNotFoundError:
        destination.mkdir(mode=0o700)
        _fsync_directory(root)
        return destination.resolve(strict=True)
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ControlV2RolloutError("web-activations must be a real directory")
    return destination.resolve(strict=True)


def _validate_committed_legacy_journal(
    root: Path,
    *,
    migration_id: str,
    previous: tuple[str, str, str],
    active: tuple[str, str, str],
) -> None:
    journal = _read_strict_json(root / "migrations" / f"{migration_id}.json")
    expected_fields = {
        "schema_version",
        "migration_id",
        "state",
        "source",
        "target",
        "source_snapshot",
        "checks",
        "created_at",
        "updated_at",
    }
    if not isinstance(journal, dict) or set(journal) != expected_fields:
        raise ControlV2RolloutError("legacy migration journal fields are invalid")
    if (
        journal.get("schema_version") != "1"
        or journal.get("migration_id") != migration_id
        or journal.get("state") != "cutover_committed"
        or _legacy_selection(journal.get("source"), label="migration source") != previous
        or _legacy_selection(journal.get("target"), label="migration target") != active
        or journal.get("source_snapshot") != f"backups/{migration_id}"
    ):
        raise ControlV2RolloutError("legacy migration journal is inconsistent with control")
    _real_directory(root / "backups" / migration_id, label="legacy migration backup")


def _legacy_selection(payload: object, *, label: str) -> tuple[str, str, str]:
    if not isinstance(payload, dict) or set(payload) != _SELECTION_V1_FIELDS:
        raise ControlV2RolloutError(f"legacy {label} selection is invalid")
    digest = payload.get("bundle_artifact_sha256")
    version = payload.get("od_version")
    generation = payload.get("data_generation")
    try:
        normalized = LaunchSelection.from_dict(
            {
                "runtime_artifact_sha256": digest,
                "web_overlay_sha256": "0" * 64,
                "od_version": version,
                "data_generation": generation,
            },
            field_name=label,
        )
    except GenerationControlError as exc:
        raise ControlV2RolloutError(f"legacy {label} selection is invalid") from exc
    return (
        normalized.runtime_artifact_sha256,
        normalized.od_version,
        normalized.data_generation,
    )


def _read_strict_json(path: Path) -> object:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise ControlV2RolloutError(f"{path.name} is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode) or path.stat().st_size > MAX_CONTROL_BYTES:
        raise ControlV2RolloutError(f"{path.name} must be a bounded regular file")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        raw = os.read(descriptor, MAX_CONTROL_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > MAX_CONTROL_BYTES:
        raise ControlV2RolloutError(f"{path.name} exceeds the size limit")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except ControlV2RolloutError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControlV2RolloutError(f"{path.name} is not valid UTF-8 JSON") from exc


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ControlV2RolloutError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _real_directory(path: Path, *, label: str) -> Path:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise ControlV2RolloutError(f"{label} is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ControlV2RolloutError(f"{label} must be a real directory")
    return path.resolve(strict=True)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
