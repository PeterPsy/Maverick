"""Canonical provenance, trust, and data-class joins for agentic egress.

Classification is deliberately resource-derived.  Callers may carry declarations
or policy identifiers alongside these records, but neither is accepted as an
input capable of changing a source data class.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Iterable

from core.egress.agentic_models import EgressProvenance, EgressTrustLevel
from core.providers.agentic_models import RuntimeDataClass


KNOWN_DATA_CLASSES: tuple[RuntimeDataClass, ...] = (
    "public",
    "workspace_internal_fake",
    "workspace_internal",
    "personal_data",
    "regulated_or_customer_data",
    "credential_or_secret",
    "host_operational_metadata",
    "unclassified",
)
KNOWN_PROVENANCE: tuple[EgressProvenance, ...] = (
    "platform_instruction",
    "runtime_context",
    "runtime_capabilities",
    "workspace_instruction",
    "agent_instruction",
    "skill_fragment",
    "finalization_instruction",
    "prompt",
    "user_input",
    "orchestration_context",
    "governed_context",
    "skill",
    "attachment",
    "app_reference",
    "tool_schema",
    "tool_result",
    "provider_state",
)
KNOWN_TRUST_LEVELS: tuple[EgressTrustLevel, ...] = (
    "trusted_platform",
    "trusted_actor",
    "untrusted_external",
    "untrusted_tool_output",
)

# A larger value is never less restrictive.  The final two classes are both
# denied remotely; keeping a stable order makes joins deterministic without
# implying that a credential can be made safe by relabelling it as host data.
_DATA_CLASS_RESTRICTION = {
    "public": 0,
    "workspace_internal_fake": 1,
    "workspace_internal": 2,
    "personal_data": 3,
    "regulated_or_customer_data": 4,
    "credential_or_secret": 5,
    "host_operational_metadata": 6,
    "unclassified": 7,
}
_TRUST_RESTRICTION = {
    "trusted_platform": 0,
    "trusted_actor": 1,
    "untrusted_external": 2,
    "untrusted_tool_output": 3,
}


@dataclass(frozen=True)
class CanonicalSourceClassification:
    """Redaction-safe classification and immutable resource identity metadata."""

    data_class: RuntimeDataClass
    provenance: EgressProvenance
    trust_level: EgressTrustLevel
    source_ref: str
    source_revision: str
    source_digest: str
    resource_identity: str
    classification_revision: int | None = None
    classification_authority_id: str = ""
    classification_authority_kind: str = ""
    classification_authority_ref: str = ""
    classification_authority_revision: int | None = None
    classification_authority_digest: str = ""
    classification_authority_policy_revision: str = ""
    classification_authority_bound: bool | None = False


@dataclass(frozen=True)
class ClassificationJoin:
    """Restrictive effective classification while retaining every source."""

    sources: tuple[CanonicalSourceClassification, ...]
    effective_data_class: RuntimeDataClass
    effective_trust_level: EgressTrustLevel


def fail_closed_classification(
    *,
    provenance: str,
    source_ref: str = "",
    source_revision: str = "",
    source_digest: str = "",
    resource_identity: str = "",
) -> CanonicalSourceClassification:
    """Return an unclassified record for absent, legacy, or inconsistent data."""
    normalized_provenance: EgressProvenance = (
        provenance if provenance in KNOWN_PROVENANCE else "tool_result"
    )  # type: ignore[assignment]
    return CanonicalSourceClassification(
        data_class="unclassified",
        provenance=normalized_provenance,
        trust_level="untrusted_external",
        source_ref=str(source_ref or ""),
        source_revision=str(source_revision or ""),
        source_digest=_valid_digest_or_empty(source_digest),
        resource_identity=str(resource_identity or ""),
        classification_revision=None,
    )


def validated_classification(
    *,
    data_class: str,
    provenance: str,
    trust_level: str,
    source_ref: str,
    source_revision: str,
    source_digest: str,
    resource_identity: str,
    classification_revision: int | None,
    classification_authority_id: str = "",
    classification_authority_kind: str = "",
    classification_authority_ref: str = "",
    classification_authority_revision: int | None = None,
    classification_authority_digest: str = "",
    classification_authority_policy_revision: str = "",
    classification_authority_bound: bool | None = False,
) -> CanonicalSourceClassification:
    """Build a canonical record, failing closed when any authority field is bad."""
    fallback = fail_closed_classification(
        provenance=provenance,
        source_ref=source_ref,
        source_revision=source_revision,
        source_digest=source_digest,
        resource_identity=resource_identity,
    )
    authority_fields_valid = (
        classification_authority_bound is False
        and not classification_authority_id
        and not classification_authority_kind
        and not classification_authority_ref
        and classification_authority_revision is None
        and not classification_authority_digest
        and not classification_authority_policy_revision
    ) or (
        classification_authority_bound is True
        and bool(str(classification_authority_id or "").strip())
        and bool(str(classification_authority_kind or "").strip())
        and bool(str(classification_authority_ref or "").strip())
        and isinstance(classification_authority_revision, int)
        and not isinstance(classification_authority_revision, bool)
        and classification_authority_revision >= 1
        and _is_sha256(classification_authority_digest)
        and bool(str(classification_authority_policy_revision or "").strip())
    )
    if (
        data_class not in KNOWN_DATA_CLASSES
        or provenance not in KNOWN_PROVENANCE
        or trust_level not in KNOWN_TRUST_LEVELS
        or not str(source_ref or "").strip()
        or not str(source_revision or "").strip()
        or not str(resource_identity or "").strip()
        or not _is_sha256(source_digest)
        or not isinstance(classification_revision, int)
        or classification_revision < 1
        or not authority_fields_valid
    ):
        return fallback
    return CanonicalSourceClassification(
        data_class=data_class,  # type: ignore[arg-type]
        provenance=provenance,  # type: ignore[arg-type]
        trust_level=trust_level,  # type: ignore[arg-type]
        source_ref=source_ref.strip(),
        source_revision=source_revision.strip(),
        source_digest=source_digest.lower(),
        resource_identity=resource_identity.strip(),
        classification_revision=classification_revision,
        classification_authority_id=str(classification_authority_id).strip(),
        classification_authority_kind=str(classification_authority_kind).strip(),
        classification_authority_ref=str(classification_authority_ref).strip(),
        classification_authority_revision=classification_authority_revision,
        classification_authority_digest=str(
            classification_authority_digest
        ).lower(),
        classification_authority_policy_revision=str(
            classification_authority_policy_revision
        ).strip(),
        classification_authority_bound=classification_authority_bound,
    )


def join_classifications(
    sources: Iterable[CanonicalSourceClassification],
) -> ClassificationJoin:
    """Join source taint monotonically; an empty or malformed join is unclassified."""
    normalized = tuple(_normalize_source(source) for source in sources)
    if not normalized:
        fallback = fail_closed_classification(provenance="provider_state")
        return ClassificationJoin(
            sources=(),
            effective_data_class=fallback.data_class,
            effective_trust_level=fallback.trust_level,
        )
    data_class = max(
        (source.data_class for source in normalized),
        key=lambda value: _DATA_CLASS_RESTRICTION[value],
    )
    trust_level = max(
        (source.trust_level for source in normalized),
        key=lambda value: _TRUST_RESTRICTION[value],
    )
    return ClassificationJoin(
        sources=normalized,
        effective_data_class=data_class,
        effective_trust_level=trust_level,
    )


def join_data_classes(values: Iterable[str]) -> RuntimeDataClass:
    """Return the restrictive class join used by redaction-safe envelopes."""
    normalized = tuple(values)
    if not normalized or any(value not in KNOWN_DATA_CLASSES for value in normalized):
        return "unclassified"
    return max(normalized, key=lambda value: _DATA_CLASS_RESTRICTION[value])  # type: ignore[return-value]


def join_trust_levels(values: Iterable[str]) -> EgressTrustLevel:
    """Return the least-trusted level, failing closed on empty or unknown input."""
    normalized = tuple(values)
    if not normalized or any(value not in KNOWN_TRUST_LEVELS for value in normalized):
        return "untrusted_external"
    return max(normalized, key=lambda value: _TRUST_RESTRICTION[value])  # type: ignore[return-value]


def content_sha256(content: bytes) -> str:
    """Return an unkeyed resource-version digest, never an audit content digest."""
    return hashlib.sha256(content).hexdigest()


def derive_content_classification(
    *,
    content: bytes,
    provenance: str,
    source_ref: str,
    sources: Iterable[CanonicalSourceClassification],
    authority_source: CanonicalSourceClassification | None = None,
) -> CanonicalSourceClassification:
    """Join source taints and bind the result to the exact composed bytes.

    Composite blocks must not inherit the classification of just one component.
    The derived identity commits to every normalized source observation while the
    source digest commits to the bytes that will actually be projected.
    """
    joined = join_classifications(sources)
    digest = content_sha256(content)
    evidence = [
        {
            "data_class": source.data_class,
            "provenance": source.provenance,
            "trust_level": source.trust_level,
            "source_ref": source.source_ref,
            "source_revision": source.source_revision,
            "source_digest": source.source_digest,
            "resource_identity": source.resource_identity,
            "classification_revision": source.classification_revision,
            "classification_authority_id": source.classification_authority_id,
            "classification_authority_kind": source.classification_authority_kind,
            "classification_authority_ref": source.classification_authority_ref,
            "classification_authority_revision": (
                source.classification_authority_revision
            ),
            "classification_authority_digest": (
                source.classification_authority_digest
            ),
            "classification_authority_policy_revision": (
                source.classification_authority_policy_revision
            ),
            "classification_authority_bound": (
                source.classification_authority_bound
            ),
        }
        for source in joined.sources
    ]
    evidence_digest = hashlib.sha256(
        json.dumps(
            evidence,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    proof_complete = bool(joined.sources) and all(
        source.classification_revision is not None for source in joined.sources
    )
    if authority_source is None:
        authority = joined_classification_authority(joined.sources)
    else:
        selected_authority = join_classifications((authority_source,)).sources[0]
        authority = (
            _classification_authority_tuple(selected_authority)
            if selected_authority in joined.sources
            else ("", "", "", None, "", "", None)
        )
    return validated_classification(
        data_class=joined.effective_data_class,
        provenance=provenance,
        trust_level=joined.effective_trust_level,
        source_ref=source_ref,
        source_revision=digest,
        source_digest=digest,
        resource_identity=f"derived-content:{evidence_digest}",
        classification_revision=1 if proof_complete else None,
        classification_authority_id=authority[0],
        classification_authority_kind=authority[1],
        classification_authority_ref=authority[2],
        classification_authority_revision=authority[3],
        classification_authority_digest=authority[4],
        classification_authority_policy_revision=authority[5],
        classification_authority_bound=authority[6],
    )


def _normalize_source(
    source: CanonicalSourceClassification,
) -> CanonicalSourceClassification:
    validated = validated_classification(
        data_class=source.data_class,
        provenance=source.provenance,
        trust_level=source.trust_level,
        source_ref=source.source_ref,
        source_revision=source.source_revision,
        source_digest=source.source_digest,
        resource_identity=source.resource_identity,
        classification_revision=source.classification_revision,
        classification_authority_id=source.classification_authority_id,
        classification_authority_kind=source.classification_authority_kind,
        classification_authority_ref=source.classification_authority_ref,
        classification_authority_revision=(
            source.classification_authority_revision
        ),
        classification_authority_digest=source.classification_authority_digest,
        classification_authority_policy_revision=(
            source.classification_authority_policy_revision
        ),
        classification_authority_bound=source.classification_authority_bound,
    )
    if validated.data_class == "unclassified" and source.data_class != "unclassified":
        return replace(validated, provenance=source.provenance)
    return validated


def joined_classification_authority(
    sources: tuple[CanonicalSourceClassification, ...],
) -> tuple[str, str, str, int | None, str, str, bool | None]:
    """Preserve one exact mutable authority or make an ambiguous join invalid."""
    if any(source.classification_authority_bound is None for source in sources):
        return ("", "", "", None, "", "", None)
    authorities = {
        (
            source.classification_authority_id,
            source.classification_authority_kind,
            source.classification_authority_ref,
            source.classification_authority_revision,
            source.classification_authority_digest,
            source.classification_authority_policy_revision,
        )
        for source in sources
        if source.classification_authority_bound is True
    }
    if not authorities:
        return ("", "", "", None, "", "", False)
    if len(authorities) != 1:
        return ("", "", "", None, "", "", None)
    authority = next(iter(authorities))
    return (*authority, True)


def _classification_authority_tuple(
    source: CanonicalSourceClassification,
) -> tuple[str, str, str, int | None, str, str, bool | None]:
    return (
        source.classification_authority_id,
        source.classification_authority_kind,
        source.classification_authority_ref,
        source.classification_authority_revision,
        source.classification_authority_digest,
        source.classification_authority_policy_revision,
        source.classification_authority_bound,
    )


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdefABCDEF" for character in text)


def _valid_digest_or_empty(value: object) -> str:
    return str(value).lower() if _is_sha256(value) else ""
