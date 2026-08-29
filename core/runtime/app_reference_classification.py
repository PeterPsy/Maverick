"""Exact resource observations and production classification for app references."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable, Protocol

from core.egress.agentic_transforms import canonical_egress_content
from core.egress.classification import (
    CanonicalSourceClassification,
    fail_closed_classification,
    join_classifications,
)
from core.workspaces.data_governance import resource_classification_for_observation


@dataclass(frozen=True)
class RuntimeAppReferenceObservation:
    """Server-owned identity/version of one materialized app reference."""

    workspace_id: str
    resource_kind: str
    resource_ref: str
    resource_identity: str
    resource_revision: str
    resource_digest: str


RuntimeAppReferenceClassificationResolver = Callable[
    [RuntimeAppReferenceObservation, dict[str, object]],
    CanonicalSourceClassification,
]


class _WorkspaceClassificationStore(Protocol):
    def get_resource_classification(
        self,
        *,
        workspace_id: str,
        resource_kind: str,
        resource_ref: str,
    ): ...


def observe_runtime_app_reference(
    *,
    workspace_id: str,
    reference: dict[str, object],
) -> RuntimeAppReferenceObservation:
    """Bind a stable app/entity key and the exact materialized reference bytes."""
    normalized_workspace_id = str(workspace_id or "").strip()
    reference_type = str(reference.get("type") or "app").strip().lower()
    app_id = str(reference.get("app_id") or "").strip()
    entity_type = str(reference.get("entity_type") or "").strip()
    entity_id = str(reference.get("entity_id") or "").strip()
    if (
        not normalized_workspace_id
        or reference_type not in {"app", "entity"}
        or not app_id
        or (reference_type == "entity" and (not entity_type or not entity_id))
    ):
        raise ValueError("agentic_app_reference_metadata_invalid")
    identity_bytes = canonical_egress_content(
        {
            "app_id": app_id,
            "entity_id": entity_id if reference_type == "entity" else "",
            "entity_type": entity_type if reference_type == "entity" else "",
            "type": reference_type,
        }
    )
    identity_digest = hashlib.sha256(identity_bytes).hexdigest()
    workspace_identity_digest = hashlib.sha256(
        canonical_egress_content(
            {
                "reference_identity": identity_digest,
                "workspace_id": normalized_workspace_id,
            }
        )
    ).hexdigest()
    content_digest = hashlib.sha256(
        canonical_egress_content(reference)
    ).hexdigest()
    return RuntimeAppReferenceObservation(
        workspace_id=normalized_workspace_id,
        resource_kind="app_reference",
        resource_ref=f"app-reference:{reference_type}:{identity_digest}",
        resource_identity=f"app-reference:{workspace_identity_digest}",
        resource_revision=content_digest,
        resource_digest=content_digest,
    )


def build_workspace_app_reference_classification_resolver(
    workspace_store: _WorkspaceClassificationStore,
) -> RuntimeAppReferenceClassificationResolver:
    """Build the production resolver over revisioned workspace governance data."""

    def resolve(
        observation: RuntimeAppReferenceObservation,
        _reference: dict[str, object],
    ) -> CanonicalSourceClassification:
        return resource_classification_for_observation(
            workspace_store.get_resource_classification(
                workspace_id=observation.workspace_id,
                resource_kind=observation.resource_kind,
                resource_ref=observation.resource_ref,
            ),
            workspace_id=observation.workspace_id,
            resource_kind=observation.resource_kind,
            resource_ref=observation.resource_ref,
            resource_identity=observation.resource_identity,
            resource_revision=observation.resource_revision,
            resource_digest=observation.resource_digest,
            provenance="app_reference",
        )

    return resolve


def classify_runtime_app_reference(
    state,
    *,
    workspace_id: str,
    reference: dict[str, object],
) -> CanonicalSourceClassification:
    """Resolve exact resource evidence and reject mismatched custom resolvers."""
    try:
        observation = observe_runtime_app_reference(
            workspace_id=workspace_id,
            reference=reference,
        )
    except (TypeError, ValueError):
        return fail_closed_classification(provenance="app_reference")
    fallback = fail_closed_classification(
        provenance="app_reference",
        source_ref=observation.resource_ref,
        source_revision=observation.resource_revision,
        source_digest=observation.resource_digest,
        resource_identity=observation.resource_identity,
    )
    resolver = getattr(
        state,
        "runtime_app_reference_classification_resolver",
        None,
    )
    if not callable(resolver):
        return fallback
    try:
        candidate = resolver(observation, dict(reference))
        normalized = join_classifications((candidate,)).sources[0]
    except Exception:
        return fallback
    if (
        normalized.provenance != "app_reference"
        or normalized.source_ref != observation.resource_ref
        or normalized.source_revision != observation.resource_revision
        or normalized.source_digest != observation.resource_digest
        or normalized.resource_identity != observation.resource_identity
    ):
        return fallback
    return normalized


__all__ = [
    "RuntimeAppReferenceClassificationResolver",
    "RuntimeAppReferenceObservation",
    "build_workspace_app_reference_classification_resolver",
    "classify_runtime_app_reference",
    "observe_runtime_app_reference",
]
