"""Strict, atomic control metadata for coordinated OpenDesign generations."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
from typing import Mapping

from opendesign_generation_model import (
    GenerationControl,
    GenerationControlError,
    GenerationTriple,
    MigrationJournal,
    reconcile_migration_control,
)


CONTROL_FILE_NAME = "control.json"
MAX_CONTROL_BYTES = 64 * 1024
_MIGRATION_RE = re.compile(r"^migration_[0-9A-Za-z][0-9A-Za-z._-]{0,79}$")
_TEMP_RE = re.compile(r"^\.control\.json\.[0-9a-f]{16}\.tmp$")
_JOURNAL_TEMP_RE = re.compile(r"^\.migration_[0-9A-Za-z][0-9A-Za-z._-]{0,79}\.json\.[0-9a-f]{16}\.tmp$")


@dataclass(frozen=True)
class RecoveryResult:
    control: GenerationControl
    active_data_dir: Path
    removed_stale_temps: tuple[str, ...]
    migration_reconciliations: tuple[str, ...]


def load_generation_control(
    root: Path,
    *,
    verified_artifacts: Mapping[str, str],
) -> GenerationControl:
    root = _validated_root(root)
    control = load_generation_control_metadata(root)
    _validate_references(root, control, verified_artifacts=verified_artifacts)
    if control.migration_id is not None:
        journal = load_migration_journal(
            root,
            control.migration_id,
            verified_artifacts=verified_artifacts,
        )
        reconcile_migration_control(control, journal)
    return control


def load_generation_control_metadata(root: Path) -> GenerationControl:
    """Read strict data-control metadata; executable runtime must use load_generation_control."""
    root = _validated_root(root)
    return GenerationControl.from_dict(_read_strict_json_file(root / CONTROL_FILE_NAME))


def write_generation_control(
    root: Path,
    control: GenerationControl,
    *,
    verified_artifacts: Mapping[str, str],
) -> None:
    root = _validated_root(root)
    normalized = GenerationControl.from_dict(control.to_dict())
    _validate_references(root, normalized, verified_artifacts=verified_artifacts)
    if normalized.migration_id is not None:
        journal = load_migration_journal(
            root,
            normalized.migration_id,
            verified_artifacts=verified_artifacts,
        )
        reconcile_migration_control(normalized, journal)
    destination = root / CONTROL_FILE_NAME
    _atomic_write_json(destination, normalized.to_dict())


def load_migration_journal(
    root: Path,
    migration_id: str,
    *,
    verified_artifacts: Mapping[str, str],
) -> MigrationJournal:
    root = _validated_root(root)
    if not _MIGRATION_RE.fullmatch(migration_id):
        raise GenerationControlError("migration_id is invalid")
    migrations_root = _validated_child_directory(root, "migrations")
    journal_path = migrations_root / f"{migration_id}.json"
    journal = MigrationJournal.from_dict(_read_strict_json_file(journal_path))
    if journal.migration_id != migration_id:
        raise GenerationControlError("migration journal id does not match its file")
    _validate_journal_references(root, journal, verified_artifacts=verified_artifacts)
    return journal


def write_migration_journal(
    root: Path,
    journal: MigrationJournal,
    *,
    verified_artifacts: Mapping[str, str],
) -> None:
    root = _validated_root(root)
    normalized = MigrationJournal.from_dict(journal.to_dict())
    _validate_journal_references(root, normalized, verified_artifacts=verified_artifacts)
    migrations_root = _validated_child_directory(root, "migrations")
    _atomic_write_json(migrations_root / f"{normalized.migration_id}.json", normalized.to_dict())


def recover_generation_control(
    root: Path,
    *,
    verified_artifacts: Mapping[str, str],
) -> RecoveryResult:
    root = _validated_root(root)
    removed: list[str] = []
    for candidate in sorted(root.iterdir(), key=lambda item: item.name):
        if not _TEMP_RE.fullmatch(candidate.name):
            continue
        mode = candidate.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise GenerationControlError(f"unsafe stale control temp: {candidate.name}")
        candidate.unlink()
        removed.append(candidate.name)
    _fsync_directory(root)
    migrations_root = _validated_child_directory(root, "migrations")
    journal_temp_removed = False
    for candidate in sorted(migrations_root.iterdir(), key=lambda item: item.name):
        if not _JOURNAL_TEMP_RE.fullmatch(candidate.name):
            continue
        mode = candidate.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise GenerationControlError(f"unsafe stale migration temp: {candidate.name}")
        candidate.unlink()
        removed.append(f"migrations/{candidate.name}")
        journal_temp_removed = True
    if journal_temp_removed:
        _fsync_directory(migrations_root)
    control = load_generation_control(root, verified_artifacts=verified_artifacts)
    active_data_dir = resolve_generation_data_dir(root, control.active)
    reconciliations: list[str] = []
    for journal_path in sorted(migrations_root.glob("migration_*.json"), key=lambda item: item.name):
        migration_id = journal_path.stem
        journal = load_migration_journal(root, migration_id, verified_artifacts=verified_artifacts)
        if migration_id == control.migration_id or journal.state == "prepared":
            reconciliation = reconcile_migration_control(control, journal)
        else:
            reconciliation = f"historical_{journal.state}"
        reconciliations.append(f"{migration_id}:{reconciliation}")
    return RecoveryResult(control, active_data_dir, tuple(removed), tuple(reconciliations))


def resolve_generation_data_dir(root: Path, triple: GenerationTriple) -> Path:
    root = _validated_root(root)
    instance_root = root / "instances"
    generation_root = instance_root / triple.data_generation
    data_root = generation_root / "data"
    for label, candidate in (
        ("instances", instance_root),
        ("generation", generation_root),
        ("generation data", data_root),
    ):
        try:
            mode = candidate.lstat().st_mode
        except FileNotFoundError as exc:
            raise GenerationControlError(f"{label} directory is missing") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise GenerationControlError(f"{label} path must be a real directory")
    try:
        data_root.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise GenerationControlError("generation data directory escapes the app data root") from exc
    return data_root


def _validate_references(
    root: Path,
    control: GenerationControl,
    *,
    verified_artifacts: Mapping[str, str],
) -> None:
    for label, triple in (("active", control.active), ("previous", control.previous)):
        if triple is None:
            continue
        _verify_artifact(triple, verified_artifacts, label=label)
        resolve_generation_data_dir(root, triple)


def _validate_journal_references(
    root: Path,
    journal: MigrationJournal,
    *,
    verified_artifacts: Mapping[str, str],
) -> None:
    for label, triple in (("source", journal.source), ("target", journal.target)):
        _verify_artifact(triple, verified_artifacts, label=f"migration {label}")
        resolve_generation_data_dir(root, triple)
    snapshot = root / PurePosixPath(journal.source_snapshot)
    try:
        mode = snapshot.lstat().st_mode
    except FileNotFoundError as exc:
        raise GenerationControlError("migration source snapshot is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise GenerationControlError("migration source snapshot must be a real directory")
    try:
        snapshot.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise GenerationControlError("migration source snapshot escapes the app data root") from exc


def _atomic_write_json(destination: Path, payload: dict[str, object]) -> None:
    parent = destination.parent
    _reject_existing_non_regular(destination)
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) > MAX_CONTROL_BYTES:
        raise GenerationControlError(f"{destination.name} exceeds the size limit")
    temp = parent / f".{destination.name}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(temp, flags, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, destination)
        _fsync_directory(parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _verify_artifact(
    triple: GenerationTriple,
    verified_artifacts: Mapping[str, str],
    *,
    label: str,
) -> None:
    verified_version = verified_artifacts.get(triple.bundle_artifact_sha256)
    if verified_version is None:
        raise GenerationControlError(f"{label} bundle artifact is not verified")
    if verified_version != triple.od_version:
        raise GenerationControlError(f"{label} artifact version does not match the triple")


def _validated_root(root: Path) -> Path:
    root = Path(root)
    try:
        mode = root.lstat().st_mode
    except FileNotFoundError as exc:
        raise GenerationControlError("OpenDesign generation root is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise GenerationControlError("OpenDesign generation root must be a real directory")
    return root.resolve(strict=True)


def _validated_child_directory(root: Path, name: str) -> Path:
    child = root / name
    try:
        mode = child.lstat().st_mode
    except FileNotFoundError as exc:
        raise GenerationControlError(f"{name} directory is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise GenerationControlError(f"{name} path must be a real directory")
    try:
        child.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise GenerationControlError(f"{name} directory escapes the app data root") from exc
    return child


def _read_strict_json_file(path: Path) -> object:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise GenerationControlError(f"{path.name} is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise GenerationControlError(f"{path.name} must be a regular file")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_CONTROL_BYTES:
            raise GenerationControlError(f"{path.name} is not a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            raw = handle.read(MAX_CONTROL_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(raw) > MAX_CONTROL_BYTES:
        raise GenerationControlError(f"{path.name} exceeds the size limit")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys)
    except GenerationControlError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationControlError(f"{path.name} is not valid UTF-8 JSON") from exc


def _reject_existing_non_regular(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise GenerationControlError(f"{path.name} must be a regular file")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GenerationControlError(f"duplicate JSON field: {key}")
        result[key] = value
    return result
