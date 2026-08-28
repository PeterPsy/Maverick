"""Provider-neutral request and streaming response contract for hosted models."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

from core.providers.agentic_models import RoutingConstraint, RuntimeDataClass


AgenticMessageRole = Literal["system", "developer", "user", "assistant"]
AgenticRequestPhase = Literal[
    "exploration",
    "finalization",
    "finalization_recovery",
]
HOSTED_FINALIZATION_INSTRUCTION = (
    "The tool catalog is closed for this request. Do not call, propose, or invent any "
    "function. Produce the final answer now using only the information already available. "
    "If the request cannot be completed from that information, explain the limitation "
    "directly instead of requesting another tool."
)
AgenticModelEventType = Literal[
    "accepted",
    "text_delta",
    "text_final",
    "tool_call",
    "usage",
    "provider_state",
    "completed",
    "error",
]


@dataclass(frozen=True)
class AgenticSourceMetadata:
    """Redaction-safe source taint; raw source content and credentials are absent."""

    source_block_digest: str
    source_data_class: RuntimeDataClass
    source_trust_level: str
    provenance: str
    source_ref: str = ""
    source_revision: str = ""
    resource_identity: str = ""
    classification_revision: int | None = None


@dataclass(frozen=True)
class AgenticRequestContentBlock:
    """One transformed block approved for the exact request destination."""

    content_block_id: str
    role: AgenticMessageRole
    data_class: RuntimeDataClass
    provenance: str
    trust_level: str
    content_type: str
    content: bytes
    source_metadata: AgenticSourceMetadata | None = None


@dataclass(frozen=True)
class AgenticToolDefinition:
    """Provider-safe tool schema with a deterministic Core mapping name."""

    name: str
    description: str
    input_schema: dict[str, object]
    source_metadata: AgenticSourceMetadata | None = None


@dataclass(frozen=True)
class AgenticToolResult:
    """One exact call/result pair already approved by egress policy."""

    provider_tool_call_id: str
    provider_tool_name: str
    content_type: str
    content: bytes
    is_error: bool
    source_metadata: AgenticSourceMetadata | None = None


@dataclass(frozen=True)
class AgenticProviderPrivateState:
    """Opaque protocol bytes visible only to the matching provider codec."""

    codec_id: str
    codec_version: str
    schema_version: str
    content_type: str
    content: bytes
    source_metadata: tuple[AgenticSourceMetadata, ...] = ()
    effective_data_class: RuntimeDataClass = "unclassified"
    effective_trust_level: str = "untrusted_external"
    provider_request_id: str | None = None
    turn_generation: str | None = None


@dataclass(frozen=True)
class AgenticModelRequest:
    """Complete normalized request passed to one provider-specific client."""

    schema_version: str
    request_id: str
    correlation_id: str
    model_id: str
    reasoning_effort: str | None
    content_blocks: tuple[AgenticRequestContentBlock, ...]
    tool_definitions: tuple[AgenticToolDefinition, ...]
    tool_results: tuple[AgenticToolResult, ...]
    provider_private_state: AgenticProviderPrivateState | None
    routing_constraint: RoutingConstraint
    max_output_tokens: int
    source_metadata: tuple[AgenticSourceMetadata, ...] = field(default_factory=tuple)
    pairing_source_journal_id: str | None = None
    pairing_source_turn_id: str | None = None
    pairing_source_request_id: str | None = None
    request_phase: AgenticRequestPhase = "exploration"


@dataclass(frozen=True)
class AgenticToolCall:
    provider_tool_call_id: str
    provider_tool_name: str
    arguments: dict[str, object] | None
    call_index: int = 0
    arguments_raw: bytes | None = None

    @property
    def ledger_arguments(self) -> dict[str, object] | bytes:
        """Return the full payload for Core-private persistence only."""
        if self.arguments is not None:
            return self.arguments
        if self.arguments_raw:
            return self.arguments_raw
        return b"null"


@dataclass(frozen=True)
class AgenticUsage:
    input_tokens: int
    output_tokens: int
    estimated_cost_microusd: int | None = None


@dataclass(frozen=True)
class AgenticModelEvent:
    """One decoded provider event; raw vendor payloads never cross this boundary."""

    event_type: AgenticModelEventType
    request_id: str
    ordinal: int
    text: str | None = None
    tool_call: AgenticToolCall | None = None
    usage: AgenticUsage | None = None
    provider_private_state: AgenticProviderPrivateState | None = None
    finish_reason: str | None = None
    upstream_id: str | None = None
    provider_response_id: str | None = None
    error_code: str | None = None


class EphemeralCredential:
    """Execution-only secret value whose repr and str never reveal content."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "EphemeralCredential(<redacted>)"

    __str__ = __repr__


class AgenticModelProviderClient(Protocol):
    """Provider codec/transport boundary consumed by the shared hosted loop."""

    def create_response(
        self,
        request: AgenticModelRequest,
        *,
        credential: EphemeralCredential | None,
    ) -> AsyncIterator[AgenticModelEvent]: ...
