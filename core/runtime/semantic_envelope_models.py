"""Models and canonical digests for the agentic semantic envelope."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Literal

from core.egress.agentic_transforms import canonical_egress_content
from core.egress.classification import CanonicalSourceClassification
from core.providers.agentic_models import RuntimeDataClass
from core.providers.agentic_protocol import AgenticMessageRole
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedContentClassification,
)


SEMANTIC_ENVELOPE_SCHEMA_VERSION = "1"
HOSTED_SEMANTIC_PROJECTION_COMPILER_ID = "maverick-hosted-semantic-projection"
HOSTED_SEMANTIC_PROJECTION_COMPILER_REVISION = "1"

SemanticBlockKind = Literal[
    "content",
    "tool_schema",
    "tool_result",
    "provider_state",
]


@dataclass(frozen=True)
class SemanticEnvelopeBlock:
    """One canonical source block before destination-specific egress projection."""

    block_id: str
    schema_version: str
    kind: SemanticBlockKind
    role: AgenticMessageRole
    provenance: str
    trust_level: str
    data_class: RuntimeDataClass
    content_type: str
    content: object
    source_ref: str
    source_revision: str
    source_digest: str
    resource_identity: str
    classification_revision: int | None
    required: bool = True


@dataclass(frozen=True)
class SemanticEnvelope:
    """Complete immutable source snapshot for one provider request."""

    schema_version: str
    session_id: str
    turn_id: str
    workdir: str
    blocks: tuple[SemanticEnvelopeBlock, ...]
    source_snapshot_digest: str


def make_semantic_block(
    blocks: list[SemanticEnvelopeBlock],
    *,
    context,
    kind: SemanticBlockKind,
    role: AgenticMessageRole,
    provenance: str,
    content_type: str,
    content: object,
    classification: HostedContentClassification,
    source_ref: str = "",
    source_revision: str = "",
    resource_identity: str = "",
) -> SemanticEnvelopeBlock:
    """Construct one content-addressed block with deterministic identity."""
    if not content_type or role not in {"system", "developer", "user", "assistant"}:
        raise HostedAgenticLoopError("semantic_block_not_projectable")
    try:
        encoded = canonical_egress_content(content)
    except (TypeError, ValueError) as error:
        raise HostedAgenticLoopError("semantic_block_not_projectable") from error
    block_id = f"semantic:{context.correlation_id}:{len(blocks)}"
    resolved_ref = source_ref or classification.source_ref or block_id
    resolved_revision = (
        source_revision or classification.source_revision or context.correlation_id
    )
    return SemanticEnvelopeBlock(
        block_id=block_id,
        schema_version=SEMANTIC_ENVELOPE_SCHEMA_VERSION,
        kind=kind,
        role=role,
        provenance=provenance,
        trust_level=classification.trust_level,
        data_class=classification.data_class,
        content_type=content_type,
        content=content,
        source_ref=resolved_ref,
        source_revision=resolved_revision,
        source_digest=hashlib.sha256(encoded).hexdigest(),
        resource_identity=(
            resource_identity or classification.resource_identity or block_id
        ),
        classification_revision=classification.classification_revision,
    )


def finalize_semantic_envelope(
    *,
    context,
    blocks: list[SemanticEnvelopeBlock],
) -> SemanticEnvelope:
    envelope = SemanticEnvelope(
        schema_version=SEMANTIC_ENVELOPE_SCHEMA_VERSION,
        session_id=context.session.session_id,
        turn_id=context.correlation_id,
        workdir=str(context.session.workdir),
        blocks=tuple(blocks),
        source_snapshot_digest="",
    )
    return SemanticEnvelope(
        schema_version=envelope.schema_version,
        session_id=envelope.session_id,
        turn_id=envelope.turn_id,
        workdir=envelope.workdir,
        blocks=envelope.blocks,
        source_snapshot_digest=canonical_digest(
            {
                "schema_version": envelope.schema_version,
                "session_id": envelope.session_id,
                "turn_id": envelope.turn_id,
                "workdir": envelope.workdir,
                "blocks": [
                    {
                        key: value
                        for key, value in asdict(block).items()
                        if key != "content"
                    }
                    for block in envelope.blocks
                ],
            }
        ),
    )


def semantic_projection_digest(
    *,
    source_snapshot_digest: str,
    compiler_id: str,
    compiler_revision: str,
    projected_metadata: tuple[object, ...],
    projection_contract: object | None = None,
) -> str:
    """Digest exact exported evidence without retaining block content."""
    return canonical_digest(
        {
            "source_snapshot_digest": source_snapshot_digest,
            "compiler_id": compiler_id,
            "compiler_revision": compiler_revision,
            "projection_contract": projection_contract,
            "blocks": [
                {
                    "block_id": str(getattr(item, "semantic_block_id", "")),
                    "schema_version": str(
                        getattr(item, "semantic_block_schema_version", "")
                    ),
                    "source_digest": str(
                        getattr(item, "semantic_source_digest", "")
                    ),
                    "egress_decision_id": str(
                        getattr(item, "egress_decision_id", "")
                    ),
                    "transformation": getattr(item, "transformation", None),
                    "exported_digest": str(
                        getattr(item, "exported_digest", "")
                    ),
                }
                for item in projected_metadata
            ],
        }
    )


def platform_classification(
    source_ref: str,
    source_revision: str,
) -> HostedContentClassification:
    return HostedContentClassification(
        "public",
        "trusted_platform",
        source_ref=source_ref,
        source_revision=source_revision,
        resource_identity=f"{source_ref}:{source_revision}",
        classification_revision=1,
    )


def canonical_classification(
    value: CanonicalSourceClassification,
) -> HostedContentClassification:
    return HostedContentClassification(
        value.data_class,
        value.trust_level,
        source_ref=value.source_ref,
        source_revision=value.source_revision,
        resource_identity=value.resource_identity,
        classification_revision=value.classification_revision,
    )


def semantic_block_classification(
    block: SemanticEnvelopeBlock,
) -> HostedContentClassification:
    return HostedContentClassification(
        block.data_class,
        block.trust_level,
        source_ref=block.source_ref,
        source_revision=block.source_revision,
        resource_identity=block.resource_identity,
        classification_revision=block.classification_revision,
    )


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
