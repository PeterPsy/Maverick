"""Canonical record for public hosted-runtime workspace content authority.

The reserved record is a direct classification decision, not a fake-data
attestation or a browser/provider declaration. Callers still bind every derived
classification to the exact bytes or resource version they observed.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
from uuid import uuid4

from core.workspaces.data_governance import (
    WorkspaceResourceClassification,
    resource_classification_is_well_formed,
)
from core.workspaces.errors import WorkspaceDataGovernanceError


RUNTIME_PUBLIC_CONTENT_AUTHORITY_KIND = "runtime_public_content_authority"
RUNTIME_PUBLIC_CONTENT_AUTHORITY_REF = "hosted-full-workspace"
RUNTIME_PUBLIC_CONTENT_AUTHORITY_POLICY_REVISION = (
    "core-hosted-public-workspace-v2"
)
_LEGACY_RUNTIME_PUBLIC_CONTENT_AUTHORITY_POLICY_REVISION = (
    "core-hosted-public-workspace-v1"
)


def build_runtime_public_content_authority_record(
    *,
    workspace_id: str,
    actor_id: str,
    active: bool,
    prior: WorkspaceResourceClassification | None = None,
    expected_revision: int = 0,
    now: datetime | None = None,
) -> WorkspaceResourceClassification:
    """Build one exact record; persistence and operator identity stay external."""
    if not _valid_identity(workspace_id) or not _valid_identity(actor_id):
        raise WorkspaceDataGovernanceError(
            "runtime_public_content_authority_invalid"
        )
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 0
    ):
        raise WorkspaceDataGovernanceError(
            "runtime_public_content_authority_revision_conflict"
        )
    if prior is not None and not (
        runtime_public_content_authority_is_valid(
            prior,
            workspace_id=workspace_id,
        )
        or _runtime_public_content_authority_is_valid_for_policy(
            prior,
            workspace_id=workspace_id,
            policy_revision=(
                _LEGACY_RUNTIME_PUBLIC_CONTENT_AUTHORITY_POLICY_REVISION
            ),
        )
    ):
        raise WorkspaceDataGovernanceError(
            "runtime_public_content_authority_invalid"
        )
    prior_revision = 0 if prior is None else prior.revision
    if prior_revision != expected_revision:
        raise WorkspaceDataGovernanceError(
            "runtime_public_content_authority_revision_conflict"
        )
    timestamp = _utc(now)
    if prior is not None and timestamp < prior.updated_at:
        raise WorkspaceDataGovernanceError(
            "runtime_public_content_authority_timestamp_invalid"
        )
    record = WorkspaceResourceClassification(
        classification_id=(
            prior.classification_id
            if prior is not None
            else f"runtime-public-content-authority-{uuid4().hex}"
        ),
        workspace_id=workspace_id,
        resource_kind=RUNTIME_PUBLIC_CONTENT_AUTHORITY_KIND,
        resource_ref=RUNTIME_PUBLIC_CONTENT_AUTHORITY_REF,
        resource_identity=f"runtime-public-content-authority:{workspace_id}",
        resource_revision="pending",
        resource_digest="0" * 64,
        data_class="public" if active else "unclassified",
        trust_level="trusted_actor" if active else "untrusted_external",
        revision=expected_revision + 1,
        classified_by_actor_id=actor_id,
        classified_at=timestamp,
        updated_at=timestamp,
    )
    digest = _record_digest(record)
    return replace(
        record,
        resource_revision=digest,
        resource_digest=digest,
    )


def runtime_public_content_authority_is_active(
    record: WorkspaceResourceClassification,
    *,
    workspace_id: str,
) -> bool:
    return (
        runtime_public_content_authority_is_valid(
            record,
            workspace_id=workspace_id,
        )
        and record.data_class == "public"
        and record.trust_level == "trusted_actor"
    )


def runtime_public_content_authority_is_valid(
    record: WorkspaceResourceClassification,
    *,
    workspace_id: str,
) -> bool:
    """Validate the reserved record and its self-authenticating revision digest."""
    return _runtime_public_content_authority_is_valid_for_policy(
        record,
        workspace_id=workspace_id,
        policy_revision=RUNTIME_PUBLIC_CONTENT_AUTHORITY_POLICY_REVISION,
    )


def _runtime_public_content_authority_is_valid_for_policy(
    record: WorkspaceResourceClassification,
    *,
    workspace_id: str,
    policy_revision: str,
) -> bool:
    if (
        not isinstance(record, WorkspaceResourceClassification)
        or not resource_classification_is_well_formed(record)
        or record.workspace_id != workspace_id
        or record.resource_kind != RUNTIME_PUBLIC_CONTENT_AUTHORITY_KIND
        or record.resource_ref != RUNTIME_PUBLIC_CONTENT_AUTHORITY_REF
        or record.resource_identity
        != f"runtime-public-content-authority:{workspace_id}"
        or record.data_class not in {"public", "unclassified"}
        or record.trust_level
        != (
            "trusted_actor"
            if record.data_class == "public"
            else "untrusted_external"
        )
    ):
        return False
    digest = _record_digest(record, policy_revision=policy_revision)
    return record.resource_revision == digest and record.resource_digest == digest


def _record_digest(
    record: WorkspaceResourceClassification,
    *,
    policy_revision: str = RUNTIME_PUBLIC_CONTENT_AUTHORITY_POLICY_REVISION,
) -> str:
    payload = {
        "policy_revision": policy_revision,
        "classification_id": record.classification_id,
        "workspace_id": record.workspace_id,
        "resource_kind": record.resource_kind,
        "resource_ref": record.resource_ref,
        "resource_identity": record.resource_identity,
        "data_class": record.data_class,
        "trust_level": record.trust_level,
        "revision": record.revision,
        "classified_by_actor_id": record.classified_by_actor_id,
        "classified_at": record.classified_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()


def _valid_identity(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value.strip()) <= 512


def _utc(value: datetime | None) -> datetime:
    resolved = value or datetime.now(tz=UTC)
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise WorkspaceDataGovernanceError(
            "runtime_public_content_authority_timestamp_invalid"
        )
    return resolved.astimezone(UTC)


__all__ = [
    "RUNTIME_PUBLIC_CONTENT_AUTHORITY_KIND",
    "RUNTIME_PUBLIC_CONTENT_AUTHORITY_POLICY_REVISION",
    "RUNTIME_PUBLIC_CONTENT_AUTHORITY_REF",
    "build_runtime_public_content_authority_record",
    "runtime_public_content_authority_is_active",
    "runtime_public_content_authority_is_valid",
]
