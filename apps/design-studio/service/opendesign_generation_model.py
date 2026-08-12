"""Strict OpenDesign launch-selection and activation-journal value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
import re


CONTROL_SCHEMA_VERSION = "2"
_CONTROL_FIELDS = {
    "schema_version",
    "active",
    "previous_release",
    "previous_web",
    "migration_id",
    "web_activation_id",
    "updated_at",
}
_SELECTION_FIELDS = {
    "runtime_artifact_sha256",
    "web_overlay_sha256",
    "od_version",
    "data_generation",
}
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
_WEB_JOURNAL_FIELDS = {
    "schema_version",
    "web_activation_id",
    "state",
    "source",
    "target",
    "readiness",
    "error",
    "created_at",
    "updated_at",
}
_JOURNAL_STATES = {"prepared", "cutover_committed", "aborted"}
_WEB_JOURNAL_STATES = {
    "prepared",
    "ready_committed",
    "rollback_restart_pending",
    "rolled_back",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_GENERATION_RE = re.compile(r"^gen_[0-9A-Za-z][0-9A-Za-z._-]{0,79}$")
_MIGRATION_RE = re.compile(r"^migration_[0-9A-Za-z][0-9A-Za-z._-]{0,79}$")
_WEB_ACTIVATION_RE = re.compile(r"^web_[0-9A-Za-z][0-9A-Za-z._-]{0,79}$")


class GenerationControlError(RuntimeError):
    """Raised when launch metadata is unsafe, unknown, or inconsistent."""


@dataclass(frozen=True)
class LaunchSelection:
    runtime_artifact_sha256: str
    web_overlay_sha256: str
    od_version: str
    data_generation: str

    @classmethod
    def from_dict(cls, payload: object, *, field_name: str) -> "LaunchSelection":
        if not isinstance(payload, dict):
            raise GenerationControlError(f"{field_name} must be an object")
        if set(payload) != _SELECTION_FIELDS:
            raise GenerationControlError(f"{field_name} contains unknown or missing fields")
        runtime_digest = _required_digest(
            payload.get("runtime_artifact_sha256"),
            f"{field_name}.runtime_artifact_sha256",
        )
        web_digest = _required_digest(
            payload.get("web_overlay_sha256"),
            f"{field_name}.web_overlay_sha256",
        )
        version = _required_text(payload.get("od_version"), f"{field_name}.od_version")
        generation = _required_text(payload.get("data_generation"), f"{field_name}.data_generation")
        if not _VERSION_RE.fullmatch(version):
            raise GenerationControlError(f"{field_name}.od_version is invalid")
        if not _GENERATION_RE.fullmatch(generation):
            raise GenerationControlError(f"{field_name}.data_generation is invalid")
        return cls(runtime_digest, web_digest, version, generation)

    def to_dict(self) -> dict[str, str]:
        return {
            "runtime_artifact_sha256": self.runtime_artifact_sha256,
            "web_overlay_sha256": self.web_overlay_sha256,
            "od_version": self.od_version,
            "data_generation": self.data_generation,
        }

    def same_runtime_and_data(self, other: "LaunchSelection") -> bool:
        return (
            self.runtime_artifact_sha256 == other.runtime_artifact_sha256
            and self.od_version == other.od_version
            and self.data_generation == other.data_generation
        )


@dataclass(frozen=True)
class GenerationControl:
    active: LaunchSelection
    previous_release: LaunchSelection | None
    previous_web: LaunchSelection | None
    migration_id: str | None
    web_activation_id: str | None
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
        active = LaunchSelection.from_dict(payload.get("active"), field_name="active")
        previous_release = _optional_selection(payload.get("previous_release"), "previous_release")
        previous_web = _optional_selection(payload.get("previous_web"), "previous_web")
        migration_id = _optional_identifier(payload.get("migration_id"), "migration_id", _MIGRATION_RE)
        web_activation_id = _optional_identifier(
            payload.get("web_activation_id"),
            "web_activation_id",
            _WEB_ACTIVATION_RE,
        )
        updated_at = _required_text(payload.get("updated_at"), "updated_at")
        _validate_rfc3339(updated_at)

        if (previous_release is None) != (migration_id is None):
            raise GenerationControlError("previous_release and migration_id must be set together")
        if previous_release is not None:
            if previous_release == active:
                raise GenerationControlError("active and previous_release must differ")
            if previous_release.data_generation == active.data_generation:
                raise GenerationControlError("release rollback selections must use different data generations")
        if (previous_web is None) != (web_activation_id is None):
            raise GenerationControlError("previous_web and web_activation_id must be set together")
        if previous_web is not None:
            _validate_web_transition(previous_web, active, label="previous_web and active")

        return cls(
            active,
            previous_release,
            previous_web,
            migration_id,
            web_activation_id,
            updated_at,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "active": self.active.to_dict(),
            "previous_release": (
                self.previous_release.to_dict() if self.previous_release is not None else None
            ),
            "previous_web": self.previous_web.to_dict() if self.previous_web is not None else None,
            "migration_id": self.migration_id,
            "web_activation_id": self.web_activation_id,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class MigrationJournal:
    migration_id: str
    state: str
    source: LaunchSelection
    target: LaunchSelection
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
        migration_id = _required_identifier(payload.get("migration_id"), "migration_id", _MIGRATION_RE)
        state = _required_text(payload.get("state"), "state")
        if state not in _JOURNAL_STATES:
            raise GenerationControlError("migration journal state is invalid")
        source = LaunchSelection.from_dict(payload.get("source"), field_name="source")
        target = LaunchSelection.from_dict(payload.get("target"), field_name="target")
        if source == target or source.data_generation == target.data_generation:
            raise GenerationControlError("migration source and target must use different selections and generations")
        source_snapshot = _required_text(payload.get("source_snapshot"), "source_snapshot")
        if PurePosixPath(source_snapshot).parts != ("backups", migration_id):
            raise GenerationControlError("source_snapshot must identify this migration backup")
        checks = _string_keyed_mapping(payload.get("checks"), "migration checks")
        created_at, updated_at = _journal_timestamps(payload)
        return cls(migration_id, state, source, target, source_snapshot, checks, created_at, updated_at)

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
class WebActivationJournal:
    web_activation_id: str
    state: str
    source: LaunchSelection
    target: LaunchSelection
    readiness: dict[str, object]
    error: str | None
    created_at: str
    updated_at: str
    schema_version: str = CONTROL_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: object) -> "WebActivationJournal":
        if not isinstance(payload, dict):
            raise GenerationControlError("web activation journal must contain an object")
        if set(payload) != _WEB_JOURNAL_FIELDS:
            raise GenerationControlError("web activation journal contains unknown or missing fields")
        if payload.get("schema_version") != CONTROL_SCHEMA_VERSION:
            raise GenerationControlError("web activation journal schema_version is unsupported")
        activation_id = _required_identifier(
            payload.get("web_activation_id"),
            "web_activation_id",
            _WEB_ACTIVATION_RE,
        )
        state = _required_text(payload.get("state"), "state")
        if state not in _WEB_JOURNAL_STATES:
            raise GenerationControlError("web activation journal state is invalid")
        source = LaunchSelection.from_dict(payload.get("source"), field_name="source")
        target = LaunchSelection.from_dict(payload.get("target"), field_name="target")
        _validate_web_transition(source, target, label="web activation source and target")
        readiness = _string_keyed_mapping(payload.get("readiness"), "web activation readiness")
        error_value = payload.get("error")
        error = None if error_value is None else _required_text(error_value, "error")
        if error is not None and len(error) > 512:
            raise GenerationControlError("web activation error exceeds the size limit")
        if state == "ready_committed" and error is not None:
            raise GenerationControlError("ready web activation cannot contain an error")
        if state in {"rollback_restart_pending", "rolled_back"} and error is None:
            raise GenerationControlError("rollback web activation state requires a bounded error")
        created_at, updated_at = _journal_timestamps(payload)
        return cls(activation_id, state, source, target, readiness, error, created_at, updated_at)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "web_activation_id": self.web_activation_id,
            "state": self.state,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "readiness": self.readiness,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def reconcile_migration_control(control: GenerationControl, journal: MigrationJournal) -> str:
    if journal.state == "prepared":
        if control.active.same_runtime_and_data(journal.source) and control.migration_id != journal.migration_id:
            return "prepared_before_cutover"
        if (
            control.active.same_runtime_and_data(journal.target)
            and control.previous_release == journal.source
            and control.migration_id == journal.migration_id
        ):
            return "replace_committed_journal_pending"
    elif journal.state == "cutover_committed":
        if (
            control.active.same_runtime_and_data(journal.target)
            and control.previous_release == journal.source
            and control.migration_id == journal.migration_id
        ):
            return "committed"
    elif journal.state == "aborted" and control.active.same_runtime_and_data(journal.source):
        return "aborted"
    raise GenerationControlError("migration journal is inconsistent with active control")


def reconcile_web_activation(control: GenerationControl, journal: WebActivationJournal) -> str:
    identifier_matches = control.web_activation_id == journal.web_activation_id
    if journal.state == "prepared":
        if control.active == journal.source and not identifier_matches:
            return "prepared_before_cutover"
        if (
            control.active == journal.target
            and control.previous_web == journal.source
            and identifier_matches
        ):
            return "activation_committed_readiness_pending"
        if (
            control.active == journal.source
            and control.previous_web == journal.target
            and identifier_matches
        ):
            return "rollback_committed_journal_pending"
    elif journal.state == "ready_committed":
        if (
            control.active == journal.target
            and control.previous_web == journal.source
            and identifier_matches
        ):
            return "ready_committed"
    elif journal.state in {"rollback_restart_pending", "rolled_back"}:
        if (
            control.active == journal.source
            and control.previous_web == journal.target
            and identifier_matches
        ):
            return journal.state
    raise GenerationControlError("web activation journal is inconsistent with active control")


def _validate_web_transition(source: LaunchSelection, target: LaunchSelection, *, label: str) -> None:
    if source == target or not source.same_runtime_and_data(target):
        raise GenerationControlError(f"{label} must differ only by web overlay digest")


def _required_digest(value: object, field_name: str) -> str:
    digest = _required_text(value, field_name)
    if not _SHA256_RE.fullmatch(digest):
        raise GenerationControlError(f"{field_name} must be a lowercase SHA-256")
    return digest


def _optional_selection(value: object, field_name: str) -> LaunchSelection | None:
    return None if value is None else LaunchSelection.from_dict(value, field_name=field_name)


def _required_identifier(value: object, field_name: str, pattern: re.Pattern[str]) -> str:
    identifier = _required_text(value, field_name)
    if not pattern.fullmatch(identifier):
        raise GenerationControlError(f"{field_name} is invalid")
    return identifier


def _optional_identifier(value: object, field_name: str, pattern: re.Pattern[str]) -> str | None:
    return None if value is None else _required_identifier(value, field_name, pattern)


def _string_keyed_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) and key for key in value):
        raise GenerationControlError(f"{label} must be an object with string keys")
    return dict(value)


def _journal_timestamps(payload: dict[str, object]) -> tuple[str, str]:
    created_at = _required_text(payload.get("created_at"), "created_at")
    updated_at = _required_text(payload.get("updated_at"), "updated_at")
    _validate_rfc3339(created_at)
    _validate_rfc3339(updated_at)
    return created_at, updated_at


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or value.strip() != value or not value:
        raise GenerationControlError(f"{field_name} must be a non-empty trimmed string")
    return value


def _validate_rfc3339(value: str) -> None:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise GenerationControlError("timestamp must be RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GenerationControlError("timestamp must include a timezone")
