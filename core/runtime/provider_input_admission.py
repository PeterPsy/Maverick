"""Core-owned classification for transient provider input admitted by a turn."""

from __future__ import annotations

import hashlib

from core.egress.agentic_transforms import canonical_egress_content
from core.egress.classification import (
    CanonicalSourceClassification,
    fail_closed_classification,
    join_classifications,
    join_trust_levels,
    validated_classification,
)
from core.runtime.provider_input_context import (
    RuntimeProviderInputClassificationResolver,
    RuntimeProviderInputObservation,
)
from core.runtime.provider_input_capture import (
    GOVERNED_CONTEXT_SOURCE_RESOURCE_KIND,
    RUNTIME_PROVIDER_INPUT_CAPTURE_REVISION,
    RUNTIME_PROVIDER_INPUT_CLASSIFIER_ID,
    RUNTIME_PROVIDER_INPUT_CLASSIFIER_REVISION,
    RUNTIME_PROVIDER_INPUT_RESOURCE_KIND,
    runtime_provider_input_source_contract,
)
from core.runtime.provider_input_governed_sources import (
    generalist_context_source_chunks,
)


RUNTIME_PROVIDER_INPUT_ADMISSION_REVISION = 4
def build_runtime_provider_input_classification_resolver(
    *,
    runtime_store,
) -> RuntimeProviderInputClassificationResolver:
    """Resolve exact transient resources through the atomic turn capture."""

    def resolve(observation, content):
        return classify_admitted_runtime_provider_input(
            observation,
            content,
            runtime_store=runtime_store,
        )

    return resolve


def classify_admitted_runtime_provider_input(
    observation: RuntimeProviderInputObservation,
    content: object,
    *,
    runtime_store=None,
) -> CanonicalSourceClassification:
    """Classify only exact transient sources materialized by Core for this turn.

    This is deliberately not a generic provenance fallback.  The accepted
    source ids and content types are the closed provider-input composition
    contract, and the classification is bound to the exact canonical bytes and
    workspace/session/turn identity supplied by that composition.
    """
    fallback = fail_closed_classification(
        provenance=str(getattr(observation, "provenance", "") or "tool_result"),
        source_ref=str(getattr(observation, "source_ref", "") or ""),
        source_revision=str(getattr(observation, "source_revision", "") or ""),
        source_digest=str(getattr(observation, "source_digest", "") or ""),
        resource_identity=str(
            getattr(observation, "resource_identity", "") or ""
        ),
    )
    if not isinstance(observation, RuntimeProviderInputObservation):
        return fallback
    if any(
        not isinstance(getattr(observation, field_name), str)
        for field_name in (
            "workspace_id",
            "session_id",
            "turn_id",
            "source_id",
            "provenance",
            "content_type",
            "source_ref",
            "source_revision",
            "source_digest",
            "resource_identity",
        )
    ):
        return fallback
    expected_source = runtime_provider_input_source_contract(
        observation.source_id
    )
    if expected_source is None:
        return fallback
    expected_provenance, expected_content_type = expected_source
    if (
        observation.provenance != expected_provenance
        or observation.content_type != expected_content_type
        or not observation.workspace_id
        or not observation.session_id
        or not observation.turn_id
    ):
        return fallback
    try:
        digest = hashlib.sha256(canonical_egress_content(content)).hexdigest()
    except (TypeError, ValueError):
        return fallback
    source_ref = f"runtime-turn:{observation.turn_id}:{observation.source_id}"
    identity = (
        f"runtime-input:{observation.workspace_id}:{observation.session_id}:"
        f"{observation.turn_id}:{observation.source_id}:{digest}"
    )
    if (
        observation.source_ref != source_ref
        or observation.source_revision != digest
        or observation.source_digest.lower() != digest
        or observation.resource_identity != identity
    ):
        return fallback
    if observation.source_id == "generalist-orchestration":
        return _classify_generalist_orchestration(
            observation,
            content,
            runtime_store=runtime_store,
            fallback=fallback,
        )
    return _captured_source_classification(
        runtime_store,
        observation=observation,
        resource_kind=RUNTIME_PROVIDER_INPUT_RESOURCE_KIND,
        resource_ref=source_ref,
        resource_identity=identity,
        resource_revision=digest,
        resource_digest=digest,
        provenance=observation.provenance,
        fallback=fallback,
    )


def _classify_generalist_orchestration(
    observation: RuntimeProviderInputObservation,
    content: object,
    *,
    runtime_store,
    fallback: CanonicalSourceClassification,
) -> CanonicalSourceClassification:
    """Join exact persisted context sources; never classify the aggregate by id."""
    chunks = generalist_context_source_chunks(content)
    if chunks is None:
        return fallback
    sources: list[CanonicalSourceClassification] = []
    for resource_ref, chunk in chunks:
        try:
            digest = hashlib.sha256(canonical_egress_content(chunk)).hexdigest()
            identity = (
                f"governed-context-source:{observation.workspace_id}:"
                f"{resource_ref}:{digest}"
            )
        except Exception:
            return fallback
        sources.append(
            _captured_source_classification(
                runtime_store,
                observation=observation,
                resource_kind=GOVERNED_CONTEXT_SOURCE_RESOURCE_KIND,
                resource_ref=resource_ref,
                resource_identity=identity,
                resource_revision=digest,
                resource_digest=digest,
                provenance="governed_context",
                fallback=fallback,
            )
        )
    joined = join_classifications(sources)
    proof_complete = bool(sources) and all(
        source.classification_revision is not None for source in sources
    )
    return validated_classification(
        data_class=joined.effective_data_class,
        provenance="governed_context",
        trust_level=join_trust_levels(
            (joined.effective_trust_level, "untrusted_external")
        ),
        source_ref=observation.source_ref,
        source_revision=observation.source_revision,
        source_digest=observation.source_digest,
        resource_identity=observation.resource_identity,
        classification_revision=(
            RUNTIME_PROVIDER_INPUT_CLASSIFIER_REVISION
            if proof_complete
            else None
        ),
    )


def _captured_source_classification(
    runtime_store,
    *,
    observation: RuntimeProviderInputObservation,
    resource_kind: str,
    resource_ref: str,
    resource_identity: str,
    resource_revision: str,
    resource_digest: str,
    provenance: str,
    fallback: CanonicalSourceClassification,
) -> CanonicalSourceClassification:
    """Resolve only an exact entry from the immutable Core turn manifest."""
    try:
        turn = runtime_store.get_turn(observation.turn_id)
        manifest = turn.provider_input_classification_manifest
    except Exception:
        return fallback
    if (
        turn.workspace_id != observation.workspace_id
        or turn.session_id != observation.session_id
        or not isinstance(manifest, dict)
        or manifest.get("schema_revision")
        != RUNTIME_PROVIDER_INPUT_CAPTURE_REVISION
        or manifest.get("classifier_id") != RUNTIME_PROVIDER_INPUT_CLASSIFIER_ID
        or manifest.get("classifier_revision")
        != RUNTIME_PROVIDER_INPUT_CLASSIFIER_REVISION
        or manifest.get("workspace_id") != observation.workspace_id
        or manifest.get("session_id") != observation.session_id
        or manifest.get("turn_id") != observation.turn_id
        or not isinstance(manifest.get("sources"), dict)
    ):
        return fallback
    entry = manifest["sources"].get(resource_ref)
    if (
        not isinstance(entry, dict)
        or entry.get("resource_kind") != resource_kind
        or entry.get("resource_ref") != resource_ref
        or entry.get("resource_identity") != resource_identity
        or entry.get("resource_revision") != resource_revision
        or str(entry.get("resource_digest") or "").lower()
        != resource_digest.lower()
        or entry.get("classification_revision")
        != RUNTIME_PROVIDER_INPUT_CLASSIFIER_REVISION
    ):
        return fallback
    return validated_classification(
        data_class=str(entry.get("data_class") or ""),
        provenance=provenance,
        trust_level=str(entry.get("trust_level") or ""),
        source_ref=resource_ref,
        source_revision=resource_revision,
        source_digest=resource_digest,
        resource_identity=resource_identity,
        classification_revision=RUNTIME_PROVIDER_INPUT_CLASSIFIER_REVISION,
    )


__all__ = [
    "RUNTIME_PROVIDER_INPUT_ADMISSION_REVISION",
    "RUNTIME_PROVIDER_INPUT_RESOURCE_KIND",
    "GOVERNED_CONTEXT_SOURCE_RESOURCE_KIND",
    "build_runtime_provider_input_classification_resolver",
    "classify_admitted_runtime_provider_input",
]
