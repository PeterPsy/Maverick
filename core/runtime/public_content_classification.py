"""Exact source classification derived from runtime-public authority."""

from __future__ import annotations

from core.egress.classification import (
    CanonicalSourceClassification,
    fail_closed_classification,
    join_classifications,
    validated_classification,
)
from core.runtime.public_content_authority import (
    runtime_public_content_authority_is_active,
)
from core.runtime.public_content_authority_store import (
    runtime_public_content_authority_for_workspace,
)
from core.workspaces.data_governance import WorkspaceResourceClassification


def classification_from_runtime_public_content_authority(
    record: WorkspaceResourceClassification | None,
    *,
    workspace_id: str,
    provenance: str,
    trust_level: str,
    source_ref: str,
    source_revision: str,
    source_digest: str,
    resource_identity: str,
    detected_data_class: str = "unclassified",
) -> CanonicalSourceClassification:
    """Bind one exact source to the active authority, with detector narrowing."""
    fallback = fail_closed_classification(
        provenance=provenance,
        source_ref=source_ref,
        source_revision=source_revision,
        source_digest=source_digest,
        resource_identity=resource_identity,
    )
    if record is None or not runtime_public_content_authority_is_active(
        record,
        workspace_id=workspace_id,
    ):
        return fallback
    data_class = (
        "public"
        if detected_data_class == "unclassified"
        else detected_data_class
    )
    return validated_classification(
        data_class=data_class,
        provenance=provenance,
        trust_level=trust_level,
        source_ref=source_ref,
        source_revision=source_revision,
        source_digest=source_digest,
        resource_identity=resource_identity,
        classification_revision=record.revision,
    )


def resolve_runtime_public_resource_classification(
    store,
    *,
    observation,
    provenance: str,
    authoritative: CanonicalSourceClassification,
) -> CanonicalSourceClassification:
    """Use broad authority only when no exact narrower record supersedes it."""
    workspace_id = str(getattr(observation, "workspace_id", "") or "")
    record = runtime_public_content_authority_for_workspace(store, workspace_id)
    public = classification_from_runtime_public_content_authority(
        record,
        workspace_id=workspace_id,
        provenance=provenance,
        trust_level="untrusted_tool_output",
        source_ref=str(getattr(observation, "resource_ref", "") or ""),
        source_revision=str(
            getattr(observation, "resource_revision", "") or ""
        ),
        source_digest=str(getattr(observation, "resource_digest", "") or ""),
        resource_identity=str(
            getattr(observation, "resource_identity", "") or ""
        ),
    )
    if authoritative.classification_revision is None:
        return public
    if public.classification_revision is None:
        return authoritative
    joined = join_classifications((authoritative, public))
    return validated_classification(
        data_class=joined.effective_data_class,
        provenance=provenance,
        trust_level=joined.effective_trust_level,
        source_ref=str(getattr(observation, "resource_ref", "") or ""),
        source_revision=str(
            getattr(observation, "resource_revision", "") or ""
        ),
        source_digest=str(getattr(observation, "resource_digest", "") or ""),
        resource_identity=str(
            getattr(observation, "resource_identity", "") or ""
        ),
        classification_revision=max(
            authoritative.classification_revision,
            record.revision if record is not None else 1,
        ),
    )


__all__ = [
    "classification_from_runtime_public_content_authority",
    "resolve_runtime_public_resource_classification",
]
