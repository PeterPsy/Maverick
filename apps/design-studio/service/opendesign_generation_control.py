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
    LaunchSelection,
    MigrationJournal,
    RuntimeActivationJournal,
    WebActivationJournal,
    reconcile_migration_control,
    reconcile_runtime_activation,
    reconcile_web_activation,
)


CONTROL_FILE_NAME = "control.json"
MAX_CONTROL_BYTES = 64 * 1024
_MIGRATION_RE = re.compile(r"^migration_[0-9A-Za-z][0-9A-Za-z._-]{0,79}$")
_WEB_ACTIVATION_RE = re.compile(r"^web_[0-9A-Za-z][0-9A-Za-z._-]{0,79}$")
_RUNTIME_ACTIVATION_RE = re.compile(r"^runtime_[0-9A-Za-z][0-9A-Za-z._-]{0,79}$")
_TEMP_RE = re.compile(r"^\.control\.json\.[0-9a-f]{16}\.tmp$")
_JOURNAL_TEMP_RE = re.compile(r"^\.migration_[0-9A-Za-z][0-9A-Za-z._-]{0,79}\.json\.[0-9a-f]{16}\.tmp$")
_WEB_JOURNAL_TEMP_RE = re.compile(r"^\.web_[0-9A-Za-z][0-9A-Za-z._-]{0,79}\.json\.[0-9a-f]{16}\.tmp$")
_RUNTIME_JOURNAL_TEMP_RE = re.compile(
    r"^\.runtime_[0-9A-Za-z][0-9A-Za-z._-]{0,79}\.json\.[0-9a-f]{16}\.tmp$"
)


@dataclass(frozen=True)
class RecoveryResult:
    control: GenerationControl
    active_data_dir: Path
    removed_stale_temps: tuple[str, ...]
    migration_reconciliations: tuple[str, ...]
    web_reconciliations: tuple[str, ...]
    runtime_reconciliations: tuple[str, ...] = ()


def load_generation_control(
    root: Path,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
) -> GenerationControl:
    root = _validated_root(root)
    control = load_generation_control_metadata(root)
    _validate_references(
        root,
        control,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
    )
    if control.migration_id is not None:
        journal = load_migration_journal(
            root,
            control.migration_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        reconcile_migration_control(control, journal)
    if control.web_activation_id is not None:
        journal = load_web_activation_journal(
            root,
            control.web_activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        reconcile_web_activation(control, journal)
    if control.runtime_activation_id is not None:
        journal = load_runtime_activation_journal(
            root,
            control.runtime_activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        reconcile_runtime_activation(control, journal)
    return control


def load_runtime_generation_control(
    root: Path,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
) -> GenerationControl:
    """Load launch metadata while requiring full verification of the active artifact.

    Retained rollback artifacts are metadata until selected by a rollback. Their
    data directories, journal and snapshot are still validated on every launch;
    the executable closure is fully verified by the rollback operation before it
    can become active.
    """
    root = _validated_root(root)
    control = load_generation_control_metadata(root)
    _verify_selection(
        control.active,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
        label="active",
    )
    resolve_generation_data_dir(root, control.active)
    if control.previous_release is not None:
        resolve_generation_data_dir(root, control.previous_release)
    if control.previous_web is not None:
        _verify_overlay(control.previous_web, verified_overlays, label="previous_web")
    if control.previous_runtime is not None:
        resolve_generation_data_dir(root, control.previous_runtime)
    if control.migration_id is not None:
        journal = load_migration_journal_metadata(root, control.migration_id)
        _validate_journal_paths(root, journal)
        reconcile_migration_control(control, journal)
    if control.web_activation_id is not None:
        journal = load_web_activation_journal_metadata(root, control.web_activation_id)
        reconcile_web_activation(control, journal)
    if control.runtime_activation_id is not None:
        journal = load_runtime_activation_journal_metadata(root, control.runtime_activation_id)
        reconcile_runtime_activation(control, journal)
    return control


def load_generation_control_metadata(root: Path) -> GenerationControl:
    """Read strict metadata only; executable callers must use a validated loader."""
    root = _validated_root(root)
    return GenerationControl.from_dict(_read_strict_json_file(root / CONTROL_FILE_NAME))


def write_generation_control(
    root: Path,
    control: GenerationControl,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
) -> None:
    root = _validated_root(root)
    normalized = GenerationControl.from_dict(control.to_dict())
    _validate_references(
        root,
        normalized,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
    )
    if normalized.migration_id is not None:
        journal = load_migration_journal(
            root,
            normalized.migration_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        reconcile_migration_control(normalized, journal)
    if normalized.web_activation_id is not None:
        journal = load_web_activation_journal(
            root,
            normalized.web_activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        reconcile_web_activation(normalized, journal)
    if normalized.runtime_activation_id is not None:
        journal = load_runtime_activation_journal(
            root,
            normalized.runtime_activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        reconcile_runtime_activation(normalized, journal)
    destination = root / CONTROL_FILE_NAME
    _atomic_write_json(destination, normalized.to_dict())


def load_migration_journal(
    root: Path,
    migration_id: str,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
) -> MigrationJournal:
    root = _validated_root(root)
    if not _MIGRATION_RE.fullmatch(migration_id):
        raise GenerationControlError("migration_id is invalid")
    migrations_root = _validated_child_directory(root, "migrations")
    journal_path = migrations_root / f"{migration_id}.json"
    journal = MigrationJournal.from_dict(_read_strict_json_file(journal_path))
    if journal.migration_id != migration_id:
        raise GenerationControlError("migration journal id does not match its file")
    _validate_journal_references(
        root,
        journal,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
    )
    return journal


def load_migration_journal_metadata(root: Path, migration_id: str) -> MigrationJournal:
    """Read strict journal metadata without asserting executable artifact trust."""
    root = _validated_root(root)
    if not _MIGRATION_RE.fullmatch(migration_id):
        raise GenerationControlError("migration_id is invalid")
    migrations_root = _validated_child_directory(root, "migrations")
    journal_path = migrations_root / f"{migration_id}.json"
    journal = MigrationJournal.from_dict(_read_strict_json_file(journal_path))
    if journal.migration_id != migration_id:
        raise GenerationControlError("migration journal id does not match its file")
    return journal


def write_migration_journal(
    root: Path,
    journal: MigrationJournal,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
) -> None:
    root = _validated_root(root)
    normalized = MigrationJournal.from_dict(journal.to_dict())
    _validate_journal_references(
        root,
        normalized,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
    )
    migrations_root = _validated_child_directory(root, "migrations")
    _atomic_write_json(migrations_root / f"{normalized.migration_id}.json", normalized.to_dict())


def load_web_activation_journal(
    root: Path,
    web_activation_id: str,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
) -> WebActivationJournal:
    root = _validated_root(root)
    journal = load_web_activation_journal_metadata(root, web_activation_id)
    _verify_selection(
        journal.source,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
        label="web activation source",
    )
    _verify_selection(
        journal.target,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
        label="web activation target",
    )
    resolve_generation_data_dir(root, journal.source)
    return journal


def load_web_activation_journal_metadata(
    root: Path,
    web_activation_id: str,
) -> WebActivationJournal:
    root = _validated_root(root)
    if not _WEB_ACTIVATION_RE.fullmatch(web_activation_id):
        raise GenerationControlError("web_activation_id is invalid")
    journals_root = _validated_child_directory(root, "web-activations")
    journal = WebActivationJournal.from_dict(
        _read_strict_json_file(journals_root / f"{web_activation_id}.json")
    )
    if journal.web_activation_id != web_activation_id:
        raise GenerationControlError("web activation journal id does not match its file")
    return journal


def write_web_activation_journal(
    root: Path,
    journal: WebActivationJournal,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
) -> None:
    root = _validated_root(root)
    normalized = WebActivationJournal.from_dict(journal.to_dict())
    for label, selection in (("source", normalized.source), ("target", normalized.target)):
        _verify_selection(
            selection,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
            label=f"web activation {label}",
        )
        resolve_generation_data_dir(root, selection)
    journals_root = _validated_child_directory(root, "web-activations")
    _atomic_write_json(
        journals_root / f"{normalized.web_activation_id}.json",
        normalized.to_dict(),
    )


def load_runtime_activation_journal(
    root: Path,
    runtime_activation_id: str,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
) -> RuntimeActivationJournal:
    journal = load_runtime_activation_journal_metadata(root, runtime_activation_id)
    for label, selection in (("source", journal.source), ("target", journal.target)):
        _verify_selection(
            selection,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
            label=f"runtime activation {label}",
        )
        resolve_generation_data_dir(root, selection)
    return journal


def load_runtime_activation_journal_metadata(
    root: Path,
    runtime_activation_id: str,
) -> RuntimeActivationJournal:
    root = _validated_root(root)
    if not _RUNTIME_ACTIVATION_RE.fullmatch(runtime_activation_id):
        raise GenerationControlError("runtime_activation_id is invalid")
    journals_root = _validated_child_directory(root, "runtime-activations")
    journal = RuntimeActivationJournal.from_dict(
        _read_strict_json_file(journals_root / f"{runtime_activation_id}.json")
    )
    if journal.runtime_activation_id != runtime_activation_id:
        raise GenerationControlError("runtime activation journal id does not match its file")
    return journal


def write_runtime_activation_journal(
    root: Path,
    journal: RuntimeActivationJournal,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
) -> None:
    root = _validated_root(root)
    normalized = RuntimeActivationJournal.from_dict(journal.to_dict())
    for label, selection in (("source", normalized.source), ("target", normalized.target)):
        _verify_selection(
            selection,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
            label=f"runtime activation {label}",
        )
        resolve_generation_data_dir(root, selection)
    journals_root = _validated_child_directory(root, "runtime-activations")
    _atomic_write_json(
        journals_root / f"{normalized.runtime_activation_id}.json",
        normalized.to_dict(),
    )


def recover_generation_control(
    root: Path,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
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
    web_root = _validated_child_directory(root, "web-activations")
    web_temp_removed = False
    for candidate in sorted(web_root.iterdir(), key=lambda item: item.name):
        if not _WEB_JOURNAL_TEMP_RE.fullmatch(candidate.name):
            continue
        mode = candidate.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise GenerationControlError(f"unsafe stale web activation temp: {candidate.name}")
        candidate.unlink()
        removed.append(f"web-activations/{candidate.name}")
        web_temp_removed = True
    if web_temp_removed:
        _fsync_directory(web_root)
    runtime_root = _ensure_recovery_directory(root, "runtime-activations")
    runtime_temp_removed = False
    for candidate in sorted(runtime_root.iterdir(), key=lambda item: item.name):
        if not _RUNTIME_JOURNAL_TEMP_RE.fullmatch(candidate.name):
            continue
        mode = candidate.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise GenerationControlError(f"unsafe stale runtime activation temp: {candidate.name}")
        candidate.unlink()
        removed.append(f"runtime-activations/{candidate.name}")
        runtime_temp_removed = True
    if runtime_temp_removed:
        _fsync_directory(runtime_root)
    control = load_generation_control(
        root,
        verified_artifacts=verified_artifacts,
        verified_overlays=verified_overlays,
    )
    active_data_dir = resolve_generation_data_dir(root, control.active)
    reconciliations: list[str] = []
    for journal_path in sorted(migrations_root.glob("migration_*.json"), key=lambda item: item.name):
        migration_id = journal_path.stem
        journal = load_migration_journal(
            root,
            migration_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        if migration_id == control.migration_id or journal.state == "prepared":
            reconciliation = reconcile_migration_control(control, journal)
        else:
            reconciliation = f"historical_{journal.state}"
        reconciliations.append(f"{migration_id}:{reconciliation}")
    web_reconciliations: list[str] = []
    for journal_path in sorted(web_root.glob("web_*.json"), key=lambda item: item.name):
        activation_id = journal_path.stem
        journal = load_web_activation_journal(
            root,
            activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        if activation_id == control.web_activation_id or journal.state == "prepared":
            reconciliation = reconcile_web_activation(control, journal)
        else:
            reconciliation = f"historical_{journal.state}"
        web_reconciliations.append(f"{activation_id}:{reconciliation}")
    runtime_reconciliations: list[str] = []
    for journal_path in sorted(runtime_root.glob("runtime_*.json"), key=lambda item: item.name):
        activation_id = journal_path.stem
        journal = load_runtime_activation_journal(
            root,
            activation_id,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
        if activation_id == control.runtime_activation_id or journal.state == "prepared":
            reconciliation = reconcile_runtime_activation(control, journal)
        else:
            reconciliation = f"historical_{journal.state}"
        runtime_reconciliations.append(f"{activation_id}:{reconciliation}")
    return RecoveryResult(
        control,
        active_data_dir,
        tuple(removed),
        tuple(reconciliations),
        tuple(web_reconciliations),
        tuple(runtime_reconciliations),
    )


def resolve_generation_data_dir(root: Path, selection: LaunchSelection) -> Path:
    root = _validated_root(root)
    instance_root = root / "instances"
    generation_root = instance_root / selection.data_generation
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
    verified_overlays: Mapping[str, object],
) -> None:
    for label, selection in (
        ("active", control.active),
        ("previous_release", control.previous_release),
        ("previous_web", control.previous_web),
        ("previous_runtime", control.previous_runtime),
    ):
        if selection is None:
            continue
        _verify_selection(
            selection,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
            label=label,
        )
        resolve_generation_data_dir(root, selection)


def _validate_journal_references(
    root: Path,
    journal: MigrationJournal,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
) -> None:
    for label, selection in (("source", journal.source), ("target", journal.target)):
        _verify_selection(
            selection,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
            label=f"migration {label}",
        )
    _validate_journal_paths(root, journal)


def _validate_journal_paths(root: Path, journal: MigrationJournal) -> None:
    for triple in (journal.source, journal.target):
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


def _verify_selection(
    selection: LaunchSelection,
    *,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    label: str,
) -> None:
    _verify_artifact(selection, verified_artifacts, label=label)
    _verify_overlay(selection, verified_overlays, label=label)


def _verify_artifact(
    selection: LaunchSelection,
    verified_artifacts: Mapping[str, str],
    *,
    label: str,
) -> None:
    verified_version = verified_artifacts.get(selection.runtime_artifact_sha256)
    if verified_version is None:
        raise GenerationControlError(f"{label} runtime artifact is not verified")
    if verified_version != selection.od_version:
        raise GenerationControlError(f"{label} artifact version does not match the triple")


def _verify_overlay(
    selection: LaunchSelection,
    verified_overlays: Mapping[str, object],
    *,
    label: str,
) -> None:
    reference = verified_overlays.get(selection.web_overlay_sha256)
    if reference is None:
        raise GenerationControlError(f"{label} web overlay is not verified")
    if isinstance(reference, Mapping):
        version = reference.get("od_version")
        compatible = reference.get("compatible_runtime_artifact_sha256")
    else:
        version = getattr(reference, "od_version", None)
        compatible = getattr(reference, "compatible_runtime_artifact_sha256", None)
    if version != selection.od_version:
        raise GenerationControlError(f"{label} web overlay version is incompatible")
    if not isinstance(compatible, (list, tuple, set, frozenset)):
        raise GenerationControlError(f"{label} web overlay compatibility record is invalid")
    if selection.runtime_artifact_sha256 not in compatible:
        raise GenerationControlError(f"{label} web overlay is incompatible with the runtime artifact")


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


def _ensure_recovery_directory(root: Path, name: str) -> Path:
    child = root / name
    if not child.exists() and not child.is_symlink():
        child.mkdir(mode=0o700)
        _fsync_directory(root)
    return _validated_child_directory(root, name)


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
