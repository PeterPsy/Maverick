"""Data-aware egress contracts for hosted agentic runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from core.providers.agentic_models import RuntimeDataClass


EgressProvenance = Literal[
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
]
EgressTrustLevel = Literal[
    "trusted_platform",
    "trusted_actor",
    "untrusted_external",
    "untrusted_tool_output",
]


@dataclass(frozen=True)
class AgenticEgressContentBlock:
    """Classification metadata kept separate from ephemeral block content."""

    content_block_id: str
    session_id: str
    turn_id: str
    workspace_id: str
    data_class: RuntimeDataClass
    provenance: EgressProvenance
    trust_level: EgressTrustLevel
    content_type: str
    source_ref: str = ""
    source_revision: str = ""
    resource_identity: str = ""
    classification_revision: int | None = None


@dataclass(frozen=True)
class AgenticEgressPolicy:
    """Exact remote destinations and data classes allowed by live policy."""

    policy_id: str
    revision: str
    allowed_data_classes: tuple[RuntimeDataClass, ...]
    allowed_provider_ids: tuple[str, ...]
    allowed_upstream_ids: tuple[str, ...]
    transform_sensitive_text: bool = True


@dataclass(frozen=True)
class AgenticEgressDecision:
    """Redaction-safe decision record containing no source or exported content."""

    decision_id: str
    session_id: str
    turn_id: str
    content_block_id: str
    destination_provider_id: str
    destination_upstream_id: str | None
    data_class: RuntimeDataClass
    provenance: EgressProvenance
    trust_level: EgressTrustLevel
    export_allowed: bool
    transformation: str | None
    source_digest: str
    exported_digest: str | None
    policy_id: str
    policy_revision: str
    reason_code: str
    decided_at: datetime
    classification_revision: int | None = None
    attestation_id: str | None = None
    attestation_revision: int | None = None


@dataclass(frozen=True)
class AgenticEgressResult:
    """Decision plus ephemeral transformed bytes for the request builder only."""

    decision: AgenticEgressDecision
    exported_content: bytes | None


class AgenticEgressDecisionStore(Protocol):
    """Append-only persistence boundary used before remote export."""

    def initialize_egress_decision(
        self,
        *,
        workspace_id: str,
        record: AgenticEgressDecision,
    ) -> AgenticEgressDecision: ...
