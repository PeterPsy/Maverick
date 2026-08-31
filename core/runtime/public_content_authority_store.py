"""Operator workflow and persistence for runtime-public content authority."""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from core.runtime.public_content_authority import (
    RUNTIME_PUBLIC_CONTENT_AUTHORITY_KIND,
    RUNTIME_PUBLIC_CONTENT_AUTHORITY_POLICY_REVISION,
    RUNTIME_PUBLIC_CONTENT_AUTHORITY_REF,
    build_runtime_public_content_authority_record,
    runtime_public_content_authority_is_active,
    runtime_public_content_authority_is_valid,
)
from core.workspaces.data_governance import (
    WorkspaceDataGovernanceAudit,
    WorkspaceResourceClassification,
)
from core.workspaces.errors import WorkspaceDataGovernanceError


def issue_runtime_public_content_authority(
    store,
    *,
    workspace_id: str,
    actor_id: str,
    expected_revision: int,
    now: datetime | None = None,
) -> WorkspaceResourceClassification:
    """CAS-issue or reactivate the explicit public-workspace classification."""
    prior = _load_record(store, workspace_id)
    record = build_runtime_public_content_authority_record(
        workspace_id=workspace_id,
        actor_id=actor_id,
        active=True,
        prior=prior,
        expected_revision=expected_revision,
        now=now,
    )
    return _persist_with_audit(
        store,
        record=record,
        actor_id=actor_id,
        expected_revision=expected_revision,
        action="workspace.runtime_public_content_authority.issue",
        reason_code="runtime_public_content_authority_issued",
    )


def revoke_runtime_public_content_authority(
    store,
    *,
    workspace_id: str,
    actor_id: str,
    expected_revision: int,
    reason: str,
    now: datetime | None = None,
) -> WorkspaceResourceClassification:
    """CAS-revoke the authority by replacing it with an unclassified record."""
    normalized_reason = str(reason or "").strip()
    if not normalized_reason or len(normalized_reason) > 512:
        raise WorkspaceDataGovernanceError(
            "runtime_public_content_authority_revocation_reason_invalid"
        )
    prior = _load_record(store, workspace_id)
    if prior is None or not runtime_public_content_authority_is_active(
        prior,
        workspace_id=workspace_id,
    ):
        raise WorkspaceDataGovernanceError(
            "runtime_public_content_authority_not_active"
        )
    record = build_runtime_public_content_authority_record(
        workspace_id=workspace_id,
        actor_id=actor_id,
        active=False,
        prior=prior,
        expected_revision=expected_revision,
        now=now,
    )
    return _persist_with_audit(
        store,
        record=record,
        actor_id=actor_id,
        expected_revision=expected_revision,
        action="workspace.runtime_public_content_authority.revoke",
        reason_code="runtime_public_content_authority_revoked",
    )


def runtime_public_content_authority_for_workspace(
    store,
    workspace_id: str,
) -> WorkspaceResourceClassification | None:
    """Load only an active, internally coherent authority record."""
    record = runtime_public_content_authority_record_for_workspace(
        store,
        workspace_id,
    )
    return (
        record
        if record is not None
        and runtime_public_content_authority_is_active(
            record,
            workspace_id=workspace_id,
        )
        else None
    )


def runtime_public_content_authority_record_for_workspace(
    store,
    workspace_id: str,
) -> WorkspaceResourceClassification | None:
    """Load an active or revoked authority record when it remains coherent."""
    record = _load_record(store, workspace_id)
    if (
        record is None
        or not runtime_public_content_authority_is_valid(
            record,
            workspace_id=workspace_id,
        )
    ):
        return None
    action, reason_code = _audit_identity(record)
    audit = _load_audit(store, _audit_id(record, action))
    return (
        record
        if audit
        == _audit_record(
            record,
            actor_id=record.classified_by_actor_id,
            expected_revision=record.revision - 1,
            action=action,
            reason_code=reason_code,
        )
        else None
    )


def runtime_public_content_authority_projection(
    record: WorkspaceResourceClassification | None,
    *,
    workspace_id: str,
) -> dict[str, object]:
    valid = (
        record is not None
        and runtime_public_content_authority_is_valid(
            record,
            workspace_id=workspace_id,
        )
    )
    active = bool(valid and record is not None and record.data_class == "public")
    return {
        "state": "active" if active else "revoked" if valid else "not_configured",
        "authoritative": active,
        "data_class": "public" if active else None,
        "policy_revision": RUNTIME_PUBLIC_CONTENT_AUTHORITY_POLICY_REVISION,
        "authority_id": (
            record.classification_id if valid and record is not None else None
        ),
        "authority_digest": (
            record.resource_digest if valid and record is not None else None
        ),
        "revision": record.revision if valid and record is not None else None,
        "updated_at": (
            record.updated_at.isoformat()
            if valid and record is not None
            else None
        ),
    }


def _load_record(store, workspace_id: str):
    if store is None or not _valid_identity(workspace_id):
        return None
    try:
        return store.get_resource_classification(
            workspace_id=workspace_id,
            resource_kind=RUNTIME_PUBLIC_CONTENT_AUTHORITY_KIND,
            resource_ref=RUNTIME_PUBLIC_CONTENT_AUTHORITY_REF,
        )
    except Exception:
        return None


def _persist_with_audit(
    store,
    *,
    record,
    actor_id,
    expected_revision,
    action,
    reason_code,
) -> WorkspaceResourceClassification:
    """Publish audit first so authority is never visible without its evidence."""
    audit = _audit_record(
        record,
        actor_id=actor_id,
        expected_revision=expected_revision,
        action=action,
        reason_code=reason_code,
    )
    try:
        store.append_data_governance_audit(audit)
    except Exception:
        if _load_audit(store, audit.audit_id) != audit:
            raise
    return store.save_resource_classification(
        record,
        expected_revision=expected_revision,
    )


def _audit_record(
    record,
    *,
    actor_id,
    expected_revision,
    action,
    reason_code,
) -> WorkspaceDataGovernanceAudit:
    return WorkspaceDataGovernanceAudit(
        audit_id=_audit_id(record, action),
        workspace_id=record.workspace_id,
        action=action,
        record_id=record.classification_id,
        actor_id=actor_id,
        expected_revision=expected_revision,
        resulting_revision=record.revision,
        outcome="succeeded",
        reason_code=reason_code,
        occurred_at=record.updated_at,
    )


def _audit_id(record, action: str) -> str:
    return "data-governance-audit-" + uuid5(
        NAMESPACE_URL,
        ":".join(
            (
                "maverick-runtime-public-content-authority",
                record.workspace_id,
                record.classification_id,
                str(record.revision),
                record.resource_digest,
                action,
            )
        ),
    ).hex


def _audit_identity(record) -> tuple[str, str]:
    if record.data_class == "public":
        return (
            "workspace.runtime_public_content_authority.issue",
            "runtime_public_content_authority_issued",
        )
    return (
        "workspace.runtime_public_content_authority.revoke",
        "runtime_public_content_authority_revoked",
    )


def _load_audit(store, audit_id: str):
    if store is None:
        return None
    loader = getattr(store, "get_data_governance_audit", None)
    if not callable(loader):
        return None
    try:
        return loader(audit_id)
    except Exception:
        return None


def _valid_identity(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value.strip()) <= 512


__all__ = [
    "issue_runtime_public_content_authority",
    "revoke_runtime_public_content_authority",
    "runtime_public_content_authority_for_workspace",
    "runtime_public_content_authority_projection",
    "runtime_public_content_authority_record_for_workspace",
]
