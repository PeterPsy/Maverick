"""Core-owned classification for transient provider input admitted by a turn."""

from __future__ import annotations

import hashlib
import re

from core.egress.agentic_transforms import canonical_egress_content
from core.egress.classification import (
    CanonicalSourceClassification,
    fail_closed_classification,
    validated_classification,
)
from core.runtime.provider_input_context import (
    RuntimeProviderInputClassificationResolver,
    RuntimeProviderInputObservation,
)


RUNTIME_PROVIDER_INPUT_ADMISSION_REVISION = 1
_INDEXED_SOURCE = re.compile(r"^(app-reference|attachment):(\d+):metadata$")
_FIXED_SOURCES = {
    "agent-instruction": ("agent_instruction", "text/plain"),
    "turn-prompt": ("user_input", "text/plain"),
    "generalist-orchestration": ("governed_context", "application/json"),
}
_INDEXED_PROVENANCE = {
    "app-reference": ("app_reference", "text/plain"),
    "attachment": ("attachment", "application/json"),
}


def build_runtime_provider_input_classification_resolver(
) -> RuntimeProviderInputClassificationResolver:
    """Return the production resolver used after Core materializes turn input."""
    return classify_admitted_runtime_provider_input


def classify_admitted_runtime_provider_input(
    observation: RuntimeProviderInputObservation,
    content: object,
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
    expected_source = _expected_source_contract(observation.source_id)
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
    return validated_classification(
        data_class="public",
        provenance=observation.provenance,
        trust_level="trusted_actor",
        source_ref=source_ref,
        source_revision=digest,
        source_digest=digest,
        resource_identity=identity,
        classification_revision=RUNTIME_PROVIDER_INPUT_ADMISSION_REVISION,
    )


def _expected_source_contract(source_id: str) -> tuple[str, str] | None:
    fixed = _FIXED_SOURCES.get(source_id)
    if fixed is not None:
        return fixed
    indexed = _INDEXED_SOURCE.fullmatch(source_id)
    if indexed is None:
        return None
    return _INDEXED_PROVENANCE[indexed.group(1)]


__all__ = [
    "RUNTIME_PROVIDER_INPUT_ADMISSION_REVISION",
    "build_runtime_provider_input_classification_resolver",
    "classify_admitted_runtime_provider_input",
]
