"""Strict, atomic control metadata for coordinated OpenDesign generations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
from typing import Mapping


CONTROL_FILE_NAME = "control.json"
CONTROL_SCHEMA_VERSION = "1"
MAX_CONTROL_BYTES = 64 * 1024
_CONTROL_FIELDS = {"schema_version", "active", "previous", "migration_id", "updated_at"}
_TRIPLE_FIELDS = {"bundle_artifact_sha256", "od_version", "data_generation"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_GENERATION_RE = re.compile(r"^gen_[0-9A-Za-z][0-9A-Za-z._-]{0,79}$")
_MIGRATION_RE = re.compile(r"^migration_[0-9A-Za-z][0-9A-Za-z._-]{0,79}$")
_TEMP_RE = re.compile(r"^\.control\.json\.[0-9a-f]{16}\.tmp$")
_JOURNAL_TEMP_RE = re.compile(r"^\.migration_[0-9A-Za-z][0-9A-Za-z._-]{0,79}\.json\.[0-9a-f]{16}\.tmp$")
_JOURNAL_FIELDS = {
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
_JOURNAL_STATES = {"prepared", "cutover_committed", "aborted"}


class GenerationControlError(RuntimeError):
    """Raised when generation metadata is unsafe, unknown, or inconsistent."""


@dataclass(frozen=True)
class GenerationTriple:
    bundle_artifact_sha256: str
    od_version: str
    data_generation: str

    @classmethod
    def from_dict(cls, payload: object, *, field_name: str) -> "GenerationTriple":
        if not isinstance(payload, dict):
            raise GenerationControlError(f"{field_name} must be an object")
        if set(payload) != _TRIPLE_FIELDS:
            raise GenerationControlError(f"{field_name} contains unknown or missing fields")
        digest = _required_text(payload.get("bundle_artifact_sha256"), f"{field_name}.bundle_artifact_sha256")
        version = _required_text(payload.get("od_version"), f"{field_name}.od_version")
        generation = _required_text(payload.get("data_generation"), f"{field_name}.data_generation")
        if not _SHA256_RE.fullmatch(digest):
            raise GenerationControlError(f"{field_name}.bundle_artifact_sha256 must be a lowercase SHA-256")
        if not _VERSION_RE.fullmatch(version):
            raise GenerationControlError(f"{field_name}.od_version is invalid")
        if not _GENERATION_RE.fullmatch(generation):
            raise GenerationControlError(f"{field_name}.data_generation is invalid")
        return cls(digest, version, generation)

    def to_dict(self) -> dict[str, str]:
        return {
            "bundle_artifact_sha256": self.bundle_artifact_sha256,
            "od_version": self.od_version,
            "data_generation": self.data_generation,
        }


@dataclass(frozen=True)
class GenerationControl:
    active: GenerationTriple
    previous: GenerationTriple | None
    migration_id: str | None
    updated_at: str
    schema_version: str = CONTROL_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: object) -> "GenerationControl":
        if not isinstance(payload, dict):
            raise GenerationControlError("control.json must contain an object")
        if set(payload) != _CONTROL_FIELDS:
            raise GenerationControlError("control.json contains unknown or missing fields")
        if payload.get("schema_version") != CONTROL_SCHEMA_VERSION:
            raise GenerationControlError("control.json schema_version is unsupported")
        active = GenerationTriple.from_dict(payload.get("active"), field_name="active")
        previous_payload = payload.get("previous")
        previous = (
            None
            if previous_payload is None
            else GenerationTriple.from_dict(previous_payload, field_name="previous")
        )
        migration_raw = payload.get("migration_id")
        migration_id = None if migration_raw is None else _required_text(migration_raw, "migration_id")
        if migration_id is not None and not _MIGRATION_RE.fullmatch(migration_id):
            raise GenerationControlError("migration_id is invalid")
        updated_at = _required_text(payload.get("updated_at"), "updated_at")
        _validate_rfc3339(updated_at)
        if previous is not None and previous == active:
            raise GenerationControlError("active and previous triples must differ")
        if previous is not None and previous.data_generation == active.data_generation:
            raise GenerationControlError("active and previous must use different data generations")
        if migration_id is None and previous is not None:
            raise GenerationControlError("previous requires migration_id")
        if migration_id is not None and previous is None:
            raise GenerationControlError("migration_id requires previous")
        return cls(
            active=active,
            previous=previous,
            migration_id=migration_id,
            updated_at=updated_at,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "active": self.active.to_dict(),
            "previous": self.previous.to_dict() if self.previous is not None else None,
            "migration_id": self.migration_id,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class MigrationJournal:
    migration_id: str
    state: str
    source: GenerationTriple
    target: GenerationTriple
    source_snapshot: str
    checks: dict[str, object]
    created_at: str
    updated_at: str
    schema_version: str = CONTROL_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: object) -> "MigrationJournal":
        if not isinstance(payload, dict):
            raise GenerationControlError("migration journal must contain an object")
        if set(payload) != _JOURNAL_FIELDS:
            raise GenerationControlError("migration journal contains unknown or missing fields")
        if payload.get("schema_version") != CONTROL_SCHEMA_VERSION:
            raise GenerationControlError("migration journal schema_version is unsupported")
        migration_id = _required_text(payload.get("migration_id"), "migration_id")
        if not _MIGRATION_RE.fullmatch(migration_id):
            raise GenerationControlError("migration journal id is invalid")
        state_value = _required_text(payload.get("state"), "state")
        if state_value not in _JOURNAL_STATES:
            raise GenerationControlError("migration journal state is invalid")
        source = GenerationTriple.from_dict(payload.get("source"), field_name="source")
        target = GenerationTriple.from_dict(payload.get("target"), field_name="target")
        if source == target:
            raise GenerationControlError("migration source and target must differ")
        if source.data_generation == target.data_generation:
            raise GenerationControlError("migration source and target must use different data generations")
        source_snapshot = _required_text(payload.get("source_snapshot"), "source_snapshot")
        snapshot_path = PurePosixPath(source_snapshot)
        if snapshot_path.parts != ("backups", migration_id):
            raise GenerationControlError("source_snapshot must identify this migration backup")
        checks = payload.get("checks")
        if not isinstance(checks, dict) or not all(isinstance(key, str) and key for key in checks):
            raise GenerationControlError("migration checks must be an object with string keys")
        created_at = _required_text(payload.get("created_at"), "created_at")
        updated_at = _required_text(payload.get("updated_at"), "updated_at")
        _validate_rfc3339(created_at)
        _validate_rfc3339(updated_at)
        return cls(
            migration_id=migration_id,
            state=state_value,
            source=source,
            target=target,
            source_snapshot=source_snapshot,
            checks=dict(checks),
            created_at=created_at,
            updated_at=updated_at,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "migration_id": self.migration_id,
            "state": self.state,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "source_snapshot": self.source_snapshot,
            "checks": self.checks,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


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
    control_path = root / CONTROL_FILE_NAME
    payload = _read_strict_json_file(control_path)
    control = GenerationControl.from_dict(payload)
    _validate_references(root, control, verified_artifacts=verified_artifacts)
    if control.migration_id is not None:
        journal = load_migration_journal(
            root,
            control.migration_id,
            verified_artifacts=verified_artifacts,
        )
        reconcile_migration_control(control, journal)
    return control


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


def reconcile_migration_control(control: GenerationControl, journal: MigrationJournal) -> str:
    if journal.state == "prepared":
        if control.active == journal.source and control.migration_id != journal.migration_id:
            return "prepared_before_cutover"
        if (
            control.active == journal.target
            and control.previous == journal.source
            and control.migration_id == journal.migration_id
        ):
            return "replace_committed_journal_pending"
    elif journal.state == "cutover_committed":
        if (
            control.active == journal.target
            and control.previous == journal.source
            and control.migration_id == journal.migration_id
        ):
            return "committed"
    elif journal.state == "aborted" and control.active == journal.source:
        return "aborted"
    raise GenerationControlError("migration journal is inconsistent with active control")


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


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or value.strip() != value or not value:
        raise GenerationControlError(f"{field_name} must be a non-empty trimmed string")
    return value


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GenerationControlError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _validate_rfc3339(value: str) -> None:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise GenerationControlError("updated_at must be RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GenerationControlError("updated_at must include a timezone")
