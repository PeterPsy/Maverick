"""Live validation for persisted mutable classification authority lineage."""

from __future__ import annotations

import hmac

from core.egress.classification import (
    CanonicalSourceClassification,
    fail_closed_classification,
    join_classifications,
    join_data_classes,
    join_trust_levels,
)
from core.runtime.public_content_authority import (
    RUNTIME_PUBLIC_CONTENT_AUTHORITY_KIND,
    RUNTIME_PUBLIC_CONTENT_AUTHORITY_POLICY_REVISION,
    RUNTIME_PUBLIC_CONTENT_AUTHORITY_REF,
)
from core.runtime.public_content_authority_store import (
    runtime_public_content_authority_for_workspace,
)
from core.workspaces.data_governance import (
    WORKSPACE_RESOURCE_CLASSIFICATION_POLICY_REVISION,
    resource_classification_is_well_formed,
)


def classification_authority_is_current(
    store,
    *,
    workspace_id: str,
    classification,
) -> bool:
    """Return true only when a bound authority is still the exact live record."""
    bound = getattr(classification, "classification_authority_bound", None)
    lineage = _lineage(classification)
    if bound is False:
        return lineage == ("", "", "", None, "", "")
    if bound is not True or not _lineage_is_well_formed(lineage):
        return False

    authority_id, kind, ref, revision, digest, policy_revision = lineage
    if policy_revision == RUNTIME_PUBLIC_CONTENT_AUTHORITY_POLICY_REVISION:
        if (
            kind != RUNTIME_PUBLIC_CONTENT_AUTHORITY_KIND
            or ref != RUNTIME_PUBLIC_CONTENT_AUTHORITY_REF
        ):
            return False
        current = runtime_public_content_authority_for_workspace(
            store,
            workspace_id,
        )
    elif policy_revision == WORKSPACE_RESOURCE_CLASSIFICATION_POLICY_REVISION:
        try:
            current = store.get_resource_classification(
                workspace_id=workspace_id,
                resource_kind=kind,
                resource_ref=ref,
            )
        except Exception:
            return False
        if current is None or not resource_classification_is_well_formed(current):
            return False
    else:
        return False
    if current is None:
        return False
    exact_record = bool(
        current.workspace_id == workspace_id
        and current.resource_kind == kind
        and current.resource_ref == ref
        and current.classification_id == authority_id
        and current.revision == revision
        and hmac.compare_digest(current.resource_digest.lower(), digest.lower())
    )
    return bool(
        exact_record
        and join_data_classes(
            (current.data_class, classification.data_class)
        )
        == classification.data_class
        and join_trust_levels(
            (current.trust_level, classification.trust_level)
        )
        == classification.trust_level
    )


def revalidate_canonical_classification(
    store,
    *,
    workspace_id: str,
    classification: CanonicalSourceClassification,
) -> CanonicalSourceClassification:
    """Fail closed when persisted lineage is legacy, partial, revoked, or changed."""
    normalized = join_classifications((classification,)).sources[0]
    if classification_authority_is_current(
        store,
        workspace_id=workspace_id,
        classification=normalized,
    ):
        return normalized
    return fail_closed_classification(
        provenance=normalized.provenance,
        source_ref=normalized.source_ref,
        source_revision=normalized.source_revision,
        source_digest=normalized.source_digest,
        resource_identity=normalized.resource_identity,
    )


def _lineage(value) -> tuple[str, str, str, int | None, str, str]:
    return (
        str(getattr(value, "classification_authority_id", "") or ""),
        str(getattr(value, "classification_authority_kind", "") or ""),
        str(getattr(value, "classification_authority_ref", "") or ""),
        getattr(value, "classification_authority_revision", None),
        str(getattr(value, "classification_authority_digest", "") or ""),
        str(
            getattr(
                value,
                "classification_authority_policy_revision",
                "",
            )
            or ""
        ),
    )


def _lineage_is_well_formed(
    lineage: tuple[str, str, str, int | None, str, str],
) -> bool:
    authority_id, kind, ref, revision, digest, policy_revision = lineage
    return bool(
        authority_id.strip()
        and kind.strip()
        and ref.strip()
        and isinstance(revision, int)
        and not isinstance(revision, bool)
        and revision >= 1
        and len(digest) == 64
        and all(character in "0123456789abcdefABCDEF" for character in digest)
        and policy_revision.strip()
    )


__all__ = [
    "classification_authority_is_current",
    "revalidate_canonical_classification",
]
