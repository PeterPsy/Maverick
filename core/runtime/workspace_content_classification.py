"""Immutable Core classification for exact workspace-owned content."""

from __future__ import annotations

from core.egress.classification import validated_classification


WORKSPACE_CONTENT_CLASSIFICATION_REVISION = 1


def exact_workspace_resource_classification(
    *,
    provenance: str,
    trust_level: str,
    source_ref: str,
    source_revision: str,
    source_digest: str,
    resource_identity: str,
):
    """Bind workspace ownership to one exact server-observed resource version."""
    return validated_classification(
        data_class="workspace_internal",
        provenance=provenance,
        trust_level=trust_level,
        source_ref=source_ref,
        source_revision=source_revision,
        source_digest=source_digest,
        resource_identity=resource_identity,
        classification_revision=WORKSPACE_CONTENT_CLASSIFICATION_REVISION,
        classification_authority_bound=False,
    )


__all__ = [
    "WORKSPACE_CONTENT_CLASSIFICATION_REVISION",
    "exact_workspace_resource_classification",
]
