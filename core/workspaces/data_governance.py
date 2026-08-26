"""Workspace-owned declarations and resource classifications.

Attestations are declarations, never data classifiers or egress grants.  Actual
resource classifications are separate CAS-governed records and must match the
identity/version observed by the reader before they are authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Literal, Protocol
from uuid import uuid4

from core.egress.classification import (
    CanonicalSourceClassification,
    fail_closed_classification,
    validated_classification,
)
from core.workspaces.errors import WorkspaceDataGovernanceError


WorkspaceAttestationStatus = Literal["active", "revoked"]


@dataclass(frozen=True)
class WorkspaceDataAttestation:
    """CAS-revisioned actor declaration scoped to a workspace or resource set."""

    attestation_id: str
    workspace_id: str
    declaration: str
    scope_type: str
    resource_prefixes: tuple[str, ...]
    status: WorkspaceAttestationStatus
    revision: int
    attested_by_actor_id: str
    attested_by_actor_kind: str
    attested_at: datetime
    updated_at: datetime
    revoked_by_actor_id: str | None = None
    revoked_at: datetime | None = None
    revocation_reason: str | None = None

    @property
    def well_formed(self) -> bool:
        """Validate persisted shape without treating revocation as authority."""
        try:
            normalized_scope = _validated_scope(
                self.scope_type,
                self.resource_prefixes,
            )
        except WorkspaceDataGovernanceError:
            return False
        base_valid = (
            _valid_identity(self.attestation_id)
            and self.attestation_id != "legacy-unverified"
            and _valid_identity(self.workspace_id)
            and self.declaration == "fake_data_only"
            and self.scope_type in {"workspace", "resource_prefixes"}
            and normalized_scope == self.resource_prefixes
            and self.status in {"active", "revoked"}
            and isinstance(self.revision, int)
            and not isinstance(self.revision, bool)
            and self.revision >= 1
            and _valid_identity(self.attested_by_actor_id)
            and _valid_identity(self.attested_by_actor_kind)
            and _is_aware_datetime(self.attested_at)
            and _is_aware_datetime(self.updated_at)
            and self.attested_at <= self.updated_at
        )
        if not base_valid:
            return False
        if self.status == "active":
            return (
                self.revoked_by_actor_id is None
                and self.revoked_at is None
                and self.revocation_reason is None
            )
        return (
            _valid_identity(self.revoked_by_actor_id)
            and _is_aware_datetime(self.revoked_at)
            and self.revoked_at == self.updated_at
            and isinstance(self.revocation_reason, str)
            and bool(self.revocation_reason.strip())
            and len(self.revocation_reason.strip()) <= 512
        )

    @property
    def authoritative(self) -> bool:
        return self.well_formed and self.status == "active"

    def covers_resource(self, resource_ref: str) -> bool:
        """Restrict fake-data eligibility without classifying the resource."""
        if not self.authoritative:
            return False
        if self.scope_type == "workspace":
            return True
        raw = str(resource_ref or "").strip()
        if not raw or raw.startswith("/") or "\x00" in raw or "\\" in raw:
            return False
        path = PurePosixPath(raw)
        if any(part in {"", ".", ".."} for part in path.parts):
            return False
        normalized = path.as_posix()
        return bool(normalized) and any(
            normalized == prefix or normalized.startswith(f"{prefix}/")
            for prefix in self.resource_prefixes
        )


@dataclass(frozen=True)
class WorkspaceResourceClassification:
    """Actual classification pinned to one resource identity and version."""

    classification_id: str
    workspace_id: str
    resource_kind: str
    resource_ref: str
    resource_identity: str
    resource_revision: str
    resource_digest: str
    data_class: str
    trust_level: str
    revision: int
    classified_by_actor_id: str
    classified_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class WorkspaceDataGovernanceAudit:
    """Append-only redaction-safe mutation evidence."""

    audit_id: str
    workspace_id: str
    action: str
    record_id: str
    actor_id: str
    expected_revision: int
    resulting_revision: int
    outcome: str
    reason_code: str
    occurred_at: datetime


class WorkspaceDataGovernanceStore(Protocol):
    """Official document-store surface consumed by the governance service."""

    def get_data_attestation(self, workspace_id: str) -> WorkspaceDataAttestation | None: ...

    def save_data_attestation(
        self,
        record: WorkspaceDataAttestation,
        *,
        expected_revision: int,
    ) -> WorkspaceDataAttestation: ...

    def append_data_governance_audit(
        self,
        record: WorkspaceDataGovernanceAudit,
    ) -> WorkspaceDataGovernanceAudit: ...


class WorkspaceDataGovernanceService:
    """Operator-side CAS service; no browser-owned inputs cross this boundary."""

    def __init__(self, store: WorkspaceDataGovernanceStore) -> None:
        self.store = store

    def issue_attestation(
        self,
        *,
        workspace_id: str,
        actor_id: str,
        actor_kind: str,
        scope_type: str,
        resource_prefixes: tuple[str, ...] = (),
        expected_revision: int,
        now: datetime | None = None,
    ) -> WorkspaceDataAttestation:
        prior = self.store.get_data_attestation(workspace_id)
        record = issue_fake_data_attestation(
            workspace_id=workspace_id,
            actor_id=actor_id,
            actor_kind=actor_kind,
            scope_type=scope_type,
            resource_prefixes=resource_prefixes,
            prior=prior,
            expected_revision=expected_revision,
            now=now,
        )
        saved = self.store.save_data_attestation(record, expected_revision=expected_revision)
        self._audit(
            record=saved,
            action="workspace.data_attestation.issue",
            actor_id=actor_id,
            expected_revision=expected_revision,
            reason_code="attestation_issued",
        )
        return saved

    def revoke_attestation(
        self,
        *,
        workspace_id: str,
        actor_id: str,
        expected_revision: int,
        reason: str,
        now: datetime | None = None,
    ) -> WorkspaceDataAttestation:
        prior = self.store.get_data_attestation(workspace_id)
        if prior is None:
            raise WorkspaceDataGovernanceError("attestation_missing")
        record = revoke_data_attestation(
            prior,
            actor_id=actor_id,
            expected_revision=expected_revision,
            reason=reason,
            now=now,
        )
        saved = self.store.save_data_attestation(record, expected_revision=expected_revision)
        self._audit(
            record=saved,
            action="workspace.data_attestation.revoke",
            actor_id=actor_id,
            expected_revision=expected_revision,
            reason_code="attestation_revoked",
        )
        return saved

    def _audit(
        self,
        *,
        record: WorkspaceDataAttestation,
        action: str,
        actor_id: str,
        expected_revision: int,
        reason_code: str,
    ) -> None:
        self.store.append_data_governance_audit(
            WorkspaceDataGovernanceAudit(
                audit_id=f"data-governance-audit-{uuid4().hex}",
                workspace_id=record.workspace_id,
                action=action,
                record_id=record.attestation_id,
                actor_id=actor_id,
                expected_revision=expected_revision,
                resulting_revision=record.revision,
                outcome="succeeded",
                reason_code=reason_code,
                occurred_at=record.updated_at,
            )
        )


def issue_fake_data_attestation(
    *,
    workspace_id: str,
    actor_id: str,
    actor_kind: str,
    scope_type: str,
    resource_prefixes: tuple[str, ...] = (),
    prior: WorkspaceDataAttestation | None = None,
    expected_revision: int = 0,
    now: datetime | None = None,
) -> WorkspaceDataAttestation:
    """Construct the next declaration revision without granting data authority."""
    _require_identity(workspace_id, "workspace_id")
    _require_identity(actor_id, "actor_id")
    _require_identity(actor_kind, "actor_kind")
    prefixes = _validated_scope(scope_type, resource_prefixes)
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 0
    ):
        raise WorkspaceDataGovernanceError("attestation_revision_conflict")
    if prior is not None and (
        not prior.well_formed or prior.workspace_id != workspace_id
    ):
        raise WorkspaceDataGovernanceError("attestation_invalid")
    prior_revision = 0 if prior is None else prior.revision
    if expected_revision != prior_revision:
        raise WorkspaceDataGovernanceError("attestation_revision_conflict")
    timestamp = _utc(now)
    if prior is not None and timestamp < prior.updated_at:
        raise WorkspaceDataGovernanceError("attestation_timestamp_invalid")
    return WorkspaceDataAttestation(
        attestation_id=prior.attestation_id if prior else f"workspace-attestation-{uuid4().hex}",
        workspace_id=workspace_id,
        declaration="fake_data_only",
        scope_type=scope_type,
        resource_prefixes=prefixes,
        status="active",
        revision=prior_revision + 1,
        attested_by_actor_id=actor_id,
        attested_by_actor_kind=actor_kind,
        attested_at=timestamp,
        updated_at=timestamp,
    )


def revoke_data_attestation(
    prior: WorkspaceDataAttestation,
    *,
    actor_id: str,
    expected_revision: int,
    reason: str,
    now: datetime | None = None,
) -> WorkspaceDataAttestation:
    """Construct a permanent explicit revocation revision."""
    _require_identity(actor_id, "actor_id")
    normalized_reason = str(reason or "").strip()
    if not normalized_reason or len(normalized_reason) > 512:
        raise WorkspaceDataGovernanceError("attestation_revocation_reason_invalid")
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 1
        or prior.revision != expected_revision
    ):
        raise WorkspaceDataGovernanceError("attestation_revision_conflict")
    if prior.status != "active":
        raise WorkspaceDataGovernanceError("attestation_not_active")
    if not prior.authoritative:
        raise WorkspaceDataGovernanceError("attestation_invalid")
    timestamp = _utc(now)
    if timestamp < prior.updated_at:
        raise WorkspaceDataGovernanceError("attestation_timestamp_invalid")
    return WorkspaceDataAttestation(
        **{
            **prior.__dict__,
            "status": "revoked",
            "revision": prior.revision + 1,
            "updated_at": timestamp,
            "revoked_by_actor_id": actor_id,
            "revoked_at": timestamp,
            "revocation_reason": normalized_reason,
        }
    )


def resource_classification_for_observation(
    record: WorkspaceResourceClassification | None,
    *,
    workspace_id: str,
    resource_kind: str,
    resource_ref: str,
    resource_identity: str,
    resource_revision: str,
    resource_digest: str,
    provenance: str,
) -> CanonicalSourceClassification:
    """Resolve a classification only when it matches the resource actually read."""
    fallback = fail_closed_classification(
        provenance=provenance,
        source_ref=resource_ref,
        source_revision=resource_revision,
        source_digest=resource_digest,
        resource_identity=resource_identity,
    )
    if record is None or (
        record.workspace_id != workspace_id
        or record.resource_kind != resource_kind
        or record.resource_ref != resource_ref
        or record.resource_identity != resource_identity
        or record.resource_revision != resource_revision
        or not isinstance(record.resource_digest, str)
        or record.resource_digest.lower() != str(resource_digest).lower()
        or record.classification_id == "legacy-unverified"
        or not isinstance(record.revision, int)
        or isinstance(record.revision, bool)
        or record.revision < 1
        or not _valid_identity(record.classified_by_actor_id)
        or not _is_aware_datetime(record.classified_at)
        or not _is_aware_datetime(record.updated_at)
        or record.classified_at > record.updated_at
    ):
        return fallback
    return validated_classification(
        data_class=record.data_class,
        provenance=provenance,
        trust_level=record.trust_level,
        source_ref=record.resource_ref,
        source_revision=record.resource_revision,
        source_digest=record.resource_digest,
        resource_identity=record.resource_identity,
        classification_revision=record.revision,
    )


def resource_classification_is_well_formed(
    record: WorkspaceResourceClassification,
) -> bool:
    """Validate an authoritative store record independently of a later read."""
    if (
        not _valid_identity(record.classification_id)
        or record.classification_id == "legacy-unverified"
        or not _valid_identity(record.workspace_id)
        or not _valid_identity(record.resource_kind)
        or not _valid_identity(record.resource_ref)
        or not _valid_identity(record.resource_identity)
        or not _valid_identity(record.resource_revision)
        or not isinstance(record.resource_digest, str)
        or not isinstance(record.revision, int)
        or isinstance(record.revision, bool)
        or record.revision < 1
        or not _valid_identity(record.classified_by_actor_id)
        or not _is_aware_datetime(record.classified_at)
        or not _is_aware_datetime(record.updated_at)
        or record.classified_at > record.updated_at
    ):
        return False
    normalized = validated_classification(
        data_class=record.data_class,
        provenance="tool_result",
        trust_level=record.trust_level,
        source_ref=record.resource_ref,
        source_revision=record.resource_revision,
        source_digest=record.resource_digest,
        resource_identity=record.resource_identity,
        classification_revision=record.revision,
    )
    return (
        normalized.data_class == record.data_class
        and normalized.trust_level == record.trust_level
        and normalized.source_ref == record.resource_ref
        and normalized.source_revision == record.resource_revision
        and normalized.source_digest == record.resource_digest.lower()
        and normalized.resource_identity == record.resource_identity
        and normalized.classification_revision == record.revision
    )


def attestation_safe_projection(
    record: WorkspaceDataAttestation | None,
) -> dict[str, object]:
    """Return a read-only browser projection containing no mutation authority."""
    if record is None:
        return {
            "state": "not_attested",
            "authoritative": False,
            "declaration": None,
            "scope": None,
            "revision": None,
            "updated_at": None,
        }
    scope = None
    try:
        prefixes = _validated_scope(record.scope_type, record.resource_prefixes)
        scope = {"type": record.scope_type, "resource_prefixes": prefixes}
    except WorkspaceDataGovernanceError:
        pass
    valid_revision = (
        record.revision
        if isinstance(record.revision, int) and not isinstance(record.revision, bool)
        else None
    )
    return {
        "state": record.status if record.well_formed else "invalid",
        "authoritative": record.authoritative,
        "declaration": record.declaration if record.declaration == "fake_data_only" else None,
        "scope": scope,
        "revision": valid_revision,
        "updated_at": _isoformat_or_none(record.updated_at),
        "attested_at": _isoformat_or_none(record.attested_at),
        "revoked_at": _isoformat_or_none(record.revoked_at),
    }


def _validated_scope(scope_type: str, prefixes: tuple[str, ...]) -> tuple[str, ...]:
    if scope_type not in {"workspace", "resource_prefixes"}:
        raise WorkspaceDataGovernanceError("attestation_scope_invalid")
    if not isinstance(prefixes, (list, tuple)):
        raise WorkspaceDataGovernanceError("attestation_scope_invalid")
    raw_values = tuple(str(value or "").strip() for value in prefixes)
    if any(
        not value
        or value.startswith("/")
        or "\x00" in value
        or "\\" in value
        for value in raw_values
    ):
        raise WorkspaceDataGovernanceError("attestation_scope_invalid")
    normalized = tuple(PurePosixPath(value).as_posix().strip("/") for value in raw_values)
    if any(
        not value
        or value == "."
        or any(part in {"", ".", ".."} for part in PurePosixPath(value).parts)
        for value in normalized
    ):
        raise WorkspaceDataGovernanceError("attestation_scope_invalid")
    if len(set(normalized)) != len(normalized):
        raise WorkspaceDataGovernanceError("attestation_scope_invalid")
    if scope_type == "workspace" and normalized:
        raise WorkspaceDataGovernanceError("attestation_scope_invalid")
    if scope_type == "resource_prefixes" and not normalized:
        raise WorkspaceDataGovernanceError("attestation_scope_invalid")
    return normalized


def _require_identity(value: str, field_name: str) -> None:
    if not _valid_identity(value):
        raise WorkspaceDataGovernanceError(f"attestation_{field_name}_invalid")


def _utc(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(tz=UTC)
    if timestamp.tzinfo is None:
        raise WorkspaceDataGovernanceError("attestation_timestamp_invalid")
    return timestamp.astimezone(UTC)


def _is_aware_datetime(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None


def _valid_identity(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    return bool(normalized) and len(normalized) <= 256 and not any(
        ord(character) < 32 for character in normalized
    )


def _isoformat_or_none(value: object) -> str | None:
    return value.isoformat() if _is_aware_datetime(value) else None
