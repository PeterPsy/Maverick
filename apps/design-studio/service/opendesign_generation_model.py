"""Strict OpenDesign generation and migration-journal value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
import re


CONTROL_SCHEMA_VERSION = "1"
_CONTROL_FIELDS = {"schema_version", "active", "previous", "migration_id", "updated_at"}
_TRIPLE_FIELDS = {"bundle_artifact_sha256", "od_version", "data_generation"}
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
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_GENERATION_RE = re.compile(r"^gen_[0-9A-Za-z][0-9A-Za-z._-]{0,79}$")
_MIGRATION_RE = re.compile(r"^migration_[0-9A-Za-z][0-9A-Za-z._-]{0,79}$")


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
        return cls(active, previous, migration_id, updated_at)

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
        state = _required_text(payload.get("state"), "state")
        if state not in _JOURNAL_STATES:
            raise GenerationControlError("migration journal state is invalid")
        source = GenerationTriple.from_dict(payload.get("source"), field_name="source")
        target = GenerationTriple.from_dict(payload.get("target"), field_name="target")
        if source == target or source.data_generation == target.data_generation:
            raise GenerationControlError("migration source and target must use different triples and generations")
        source_snapshot = _required_text(payload.get("source_snapshot"), "source_snapshot")
        if PurePosixPath(source_snapshot).parts != ("backups", migration_id):
            raise GenerationControlError("source_snapshot must identify this migration backup")
        checks = payload.get("checks")
        if not isinstance(checks, dict) or not all(isinstance(key, str) and key for key in checks):
            raise GenerationControlError("migration checks must be an object with string keys")
        created_at = _required_text(payload.get("created_at"), "created_at")
        updated_at = _required_text(payload.get("updated_at"), "updated_at")
        _validate_rfc3339(created_at)
        _validate_rfc3339(updated_at)
        return cls(migration_id, state, source, target, source_snapshot, dict(checks), created_at, updated_at)

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


def reconcile_migration_control(control: GenerationControl, journal: MigrationJournal) -> str:
    if journal.state == "prepared":
        if control.active == journal.source and control.migration_id != journal.migration_id:
            return "prepared_before_cutover"
        if control.active == journal.target and control.previous == journal.source and control.migration_id == journal.migration_id:
            return "replace_committed_journal_pending"
    elif journal.state == "cutover_committed":
        if control.active == journal.target and control.previous == journal.source and control.migration_id == journal.migration_id:
            return "committed"
    elif journal.state == "aborted" and control.active == journal.source:
        return "aborted"
    raise GenerationControlError("migration journal is inconsistent with active control")


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or value.strip() != value or not value:
        raise GenerationControlError(f"{field_name} must be a non-empty trimmed string")
    return value


def _validate_rfc3339(value: str) -> None:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise GenerationControlError("updated_at must be RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GenerationControlError("updated_at must include a timezone")
