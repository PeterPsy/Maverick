"""Immutable hosted harness recipes selected by pinned execution profiles."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json

from core.providers.agentic_models import AgenticContextPolicy, ModelRevisionPolicy
from core.providers.google_interactions_client import (
    GOOGLE_AGENTIC_MODEL_ID,
    GOOGLE_AGENTIC_MODEL_REVISION,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_MODEL_ID,
    OPENROUTER_AGENTIC_MODEL_REVISION,
    OPENROUTER_AGENTIC_UPSTREAM_ID,
)
from core.runtime.full_workspace_contract import FULL_WORKSPACE_CONTRACT_REVISION
from core.runtime.semantic_envelope_models import (
    HOSTED_SEMANTIC_PROJECTION_COMPILER_REVISION,
)


HOSTED_CONTEXT_POLICY_REVISION = "p4-context-v4"
HOSTED_TOOL_CONTRACT_REVISION = FULL_WORKSPACE_CONTRACT_REVISION


@dataclass(frozen=True)
class HostedProviderSupportFlags:
    """Fine-grained endpoint behavior included in the recipe catalog digest."""

    streaming: bool
    usage_accounting: bool
    tool_calling: bool
    supports_empty_tool_catalog: bool
    supports_tool_choice_none: bool
    omits_tools_when_empty: bool
    parallel_tool_calls: bool
    cooperative_cancellation: bool
    continuation_mode: str
    reasoning_efforts: tuple[str, ...]
    attachment_modalities: tuple[str, ...]
    input_token_limit: int
    output_token_limit: int


@dataclass(frozen=True)
class HostedHarnessRecipeManifest:
    """Data-only identity for one exact provider/model harness composition."""

    recipe_id: str
    revision: str
    model_provider_id: str
    model_id: str
    model_revision: str
    model_revision_policy: ModelRevisionPolicy
    provider_protocol: str
    provider_api_version: str | None
    endpoint_id: str
    upstream_ids: tuple[str, ...]
    state_mode: str
    semantic_projection_compiler_revision: str
    tool_contract_revision: str
    context_policy: AgenticContextPolicy
    support_flags: HostedProviderSupportFlags

    @property
    def capability_catalog_digest(self) -> str:
        return _digest(
            {
                "recipe_id": self.recipe_id,
                "revision": self.revision,
                "model_provider_id": self.model_provider_id,
                "model_id": self.model_id,
                "model_revision": self.model_revision,
                "model_revision_policy": self.model_revision_policy,
                "provider_protocol": self.provider_protocol,
                "provider_api_version": self.provider_api_version,
                "endpoint_id": self.endpoint_id,
                "upstream_ids": self.upstream_ids,
                "support_flags": asdict(self.support_flags),
            }
        )

    @property
    def recipe_digest(self) -> str:
        return _digest(
            {
                **asdict(self),
                "capability_catalog_digest": self.capability_catalog_digest,
            }
        )


def hosted_full_context_policy() -> AgenticContextPolicy:
    """Return the common bounded policy certified by the P4 hosted recipes."""
    return AgenticContextPolicy(
        revision=HOSTED_CONTEXT_POLICY_REVISION,
        max_request_input_tokens=262_144,
        context_reserve_tokens=32_768,
        compaction_mode="provider_history",
        compaction_trigger_tokens=196_608,
        max_compacted_state_bytes=524_288,
        summary_max_bytes=4_096,
        tool_result_inline_bytes=16_384,
        tool_result_summary_bytes=8_192,
        attachment_projection_mode="workspace_reference",
        steering_delivery_mode="safe_next_turn",
        max_same_turn_steering_messages=0,
    )


GOOGLE_GOVERNED_WORKSPACE_RECIPE = HostedHarnessRecipeManifest(
    recipe_id="maverick-google-interactions-governed-workspace",
    revision="24",
    model_provider_id="google-ai-studio",
    model_id=GOOGLE_AGENTIC_MODEL_ID,
    model_revision=GOOGLE_AGENTIC_MODEL_REVISION,
    model_revision_policy="exact",
    provider_protocol="google-interactions",
    provider_api_version="v1",
    endpoint_id="google-generativelanguage-v1-interactions",
    upstream_ids=(),
    state_mode="stateless",
    semantic_projection_compiler_revision=(
        HOSTED_SEMANTIC_PROJECTION_COMPILER_REVISION
    ),
    tool_contract_revision=HOSTED_TOOL_CONTRACT_REVISION,
    context_policy=hosted_full_context_policy(),
    support_flags=HostedProviderSupportFlags(
        streaming=True,
        usage_accounting=True,
        tool_calling=True,
        supports_empty_tool_catalog=True,
        supports_tool_choice_none=False,
        omits_tools_when_empty=True,
        parallel_tool_calls=False,
        cooperative_cancellation=True,
        continuation_mode="core-managed-stateless-history",
        reasoning_efforts=("high",),
        attachment_modalities=("file",),
        input_token_limit=1_048_576,
        output_token_limit=65_536,
    ),
)


OPENROUTER_GOVERNED_WORKSPACE_RECIPE = HostedHarnessRecipeManifest(
    recipe_id="maverick-openrouter-chat-governed-workspace",
    revision="24",
    model_provider_id="openrouter",
    model_id=OPENROUTER_AGENTIC_MODEL_ID,
    model_revision=OPENROUTER_AGENTIC_MODEL_REVISION,
    model_revision_policy="provider_alias",
    provider_protocol="openrouter-chat-completions",
    provider_api_version="v1",
    endpoint_id="openrouter-chat-completions-v1",
    upstream_ids=(OPENROUTER_AGENTIC_UPSTREAM_ID,),
    state_mode="client-managed-history",
    semantic_projection_compiler_revision=(
        HOSTED_SEMANTIC_PROJECTION_COMPILER_REVISION
    ),
    tool_contract_revision=HOSTED_TOOL_CONTRACT_REVISION,
    context_policy=hosted_full_context_policy(),
    support_flags=HostedProviderSupportFlags(
        streaming=True,
        usage_accounting=True,
        tool_calling=True,
        supports_empty_tool_catalog=False,
        supports_tool_choice_none=False,
        omits_tools_when_empty=True,
        parallel_tool_calls=False,
        cooperative_cancellation=True,
        continuation_mode="core-managed-chat-history",
        reasoning_efforts=("minimal", "low", "medium", "high"),
        attachment_modalities=("file",),
        input_token_limit=1_048_576,
        output_token_limit=65_536,
    ),
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "GOOGLE_GOVERNED_WORKSPACE_RECIPE",
    "HOSTED_CONTEXT_POLICY_REVISION",
    "HOSTED_TOOL_CONTRACT_REVISION",
    "HostedHarnessRecipeManifest",
    "HostedProviderSupportFlags",
    "OPENROUTER_GOVERNED_WORKSPACE_RECIPE",
    "hosted_full_context_policy",
]
