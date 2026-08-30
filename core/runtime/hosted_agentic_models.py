"""Configuration and stable errors for the shared hosted agentic loop."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable

from core.providers.agentic_models import AgenticRuntimePolicy, RuntimeDataClass
from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticRequestPhase,
    EphemeralCredential,
)
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.tool_catalog import RuntimeToolActorContext
from core.runtime.tool_orchestrator import RuntimeToolOrchestrator
from core.runtime.runtime_cancellation import RuntimeCancellationSignal


@dataclass(frozen=True)
class HostedContentClassification:
    data_class: RuntimeDataClass
    trust_level: str
    source_ref: str = ""
    source_revision: str = ""
    resource_identity: str = ""
    classification_revision: int | None = None
    content_digest: str = ""


@dataclass(frozen=True)
class HostedProviderPrivateCodec:
    codec_id: str
    codec_version: str
    schema_version: str
    content_type: str


@dataclass(frozen=True)
class HostedProviderStateInspection:
    """Redaction-safe pairing facts decoded by the exact pinned codec."""

    pending_tool_calls: tuple[tuple[str, str], ...]
    consumed_tool_call_ids: tuple[str, ...]


HostedProviderStateInspector = Callable[[bytes], HostedProviderStateInspection]


HostedContentClassifier = Callable[[object, str, object], HostedContentClassification]
HostedCredentialResolver = Callable[[object], EphemeralCredential | None]
HostedPolicyResolver = Callable[[object], AgenticRuntimePolicy]
HostedAuthorityRefresher = Callable[[object], EffectiveRuntimeAuthority]
HostedActorContextResolver = Callable[[object], RuntimeToolActorContext]
HostedToolOrchestratorResolver = Callable[
    [object, RuntimeToolActorContext], RuntimeToolOrchestrator
]
HostedCostEstimator = Callable[[AgenticModelRequest], int | None]
HostedTurnStatusCallback = Callable[[str, str], None]
HostedAgenticRequestPhase = AgenticRequestPhase


@dataclass(frozen=True)
class HostedFinalizationPolicy:
    """Adapter-pinned resources protected for terminal hosted requests."""

    exploration_max_output_tokens: int
    finalization_max_output_tokens: int
    finalization_cost_reserve_microusd_per_attempt: int
    finalization_time_reserve_seconds_per_attempt: float
    max_recovery_attempts: int = 1

    def __post_init__(self) -> None:
        integer_limits = (
            self.exploration_max_output_tokens,
            self.finalization_max_output_tokens,
        )
        if any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
            for value in integer_limits
        ):
            raise ValueError("Hosted finalization output limits must be positive integers.")
        cost = self.finalization_cost_reserve_microusd_per_attempt
        if not isinstance(cost, int) or isinstance(cost, bool) or cost < 0:
            raise ValueError("Hosted finalization cost reserve must be non-negative.")
        time_reserve = self.finalization_time_reserve_seconds_per_attempt
        if (
            not isinstance(time_reserve, (int, float))
            or isinstance(time_reserve, bool)
            or not math.isfinite(time_reserve)
            or time_reserve <= 0
        ):
            raise ValueError("Hosted finalization time reserve must be positive.")
        if (
            not isinstance(self.max_recovery_attempts, int)
            or isinstance(self.max_recovery_attempts, bool)
            or self.max_recovery_attempts not in {0, 1}
        ):
            raise ValueError("Hosted finalization permits at most one recovery attempt.")

    @property
    def reserved_provider_steps(self) -> int:
        return 1 + self.max_recovery_attempts

    @property
    def reserved_output_tokens(self) -> int:
        return self.finalization_max_output_tokens * self.reserved_provider_steps

    @property
    def reserved_cost_microusd(self) -> int:
        return (
            self.finalization_cost_reserve_microusd_per_attempt
            * self.reserved_provider_steps
        )

    @property
    def reserved_time_seconds(self) -> float:
        return (
            self.finalization_time_reserve_seconds_per_attempt
            * self.reserved_provider_steps
        )


class HostedAgenticLoopError(RuntimeError):
    """Normalized hosted-loop failure without raw provider detail."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def raise_if_hosted_cancelled(cancellation: RuntimeCancellationSignal) -> None:
    if cancellation.is_set():
        raise HostedAgenticLoopError("runtime_cancelled")
