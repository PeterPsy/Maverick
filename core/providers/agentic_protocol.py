"""Provider-neutral request and streaming response contract for hosted models."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

from core.providers.agentic_models import RoutingConstraint, RuntimeDataClass


AgenticMessageRole = Literal["system", "developer", "user", "assistant"]
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
class AgenticRequestContentBlock:
    """One transformed block approved for the exact request destination."""

    content_block_id: str
    role: AgenticMessageRole
    data_class: RuntimeDataClass
    provenance: str
    trust_level: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class AgenticToolDefinition:
    """Provider-safe tool schema with a deterministic Core mapping name."""

    name: str
    description: str
    input_schema: dict[str, object]


@dataclass(frozen=True)
class AgenticToolResult:
    """One exact call/result pair already approved by egress policy."""

    provider_tool_call_id: str
    provider_tool_name: str
    content_type: str
    content: bytes
    is_error: bool


@dataclass(frozen=True)
class AgenticProviderPrivateState:
    """Opaque protocol bytes visible only to the matching provider codec."""

    codec_id: str
    codec_version: str
    schema_version: str
    content_type: str
    content: bytes


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


@dataclass(frozen=True)
class AgenticToolCall:
    provider_tool_call_id: str
    provider_tool_name: str
    arguments: dict[str, object]


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
