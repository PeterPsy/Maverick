"""Configuration and stable errors for the shared hosted agentic loop."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Callable

from core.providers.agentic_models import AgenticRuntimePolicy, RuntimeDataClass
from core.providers.agentic_protocol import AgenticModelRequest, EphemeralCredential
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.tool_catalog import RuntimeToolActorContext


@dataclass(frozen=True)
class HostedContentClassification:
    data_class: RuntimeDataClass
    trust_level: str


@dataclass(frozen=True)
class HostedProviderPrivateCodec:
    codec_id: str
    codec_version: str
    schema_version: str
    content_type: str


HostedContentClassifier = Callable[[str, object], HostedContentClassification]
HostedCredentialResolver = Callable[[object], EphemeralCredential | None]
HostedPolicyResolver = Callable[[object], AgenticRuntimePolicy]
HostedAuthorityRefresher = Callable[[object], EffectiveRuntimeAuthority]
HostedActorContextResolver = Callable[[object], RuntimeToolActorContext]
HostedCostEstimator = Callable[[AgenticModelRequest], int | None]
HostedTurnStatusCallback = Callable[[str, str], None]


class HostedAgenticLoopError(RuntimeError):
    """Normalized hosted-loop failure without raw provider detail."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def raise_if_hosted_cancelled(cancellation: Event) -> None:
    if cancellation.is_set():
        raise HostedAgenticLoopError("runtime_cancelled")
