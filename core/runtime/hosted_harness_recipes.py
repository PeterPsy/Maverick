"""Concrete hosted provider/model runtime settings."""

from __future__ import annotations

from dataclasses import dataclass

from core.providers.agentic_models import AgenticContextPolicy, ModelRevisionPolicy
from core.providers.google_interactions_client import (
    GOOGLE_AGENTIC_MODEL_ID,
    GOOGLE_AGENTIC_MODEL_REVISION,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_MODEL_ID,
    OPENROUTER_AGENTIC_MODEL_REVISION,
    OPENROUTER_AGENTIC_REASONING_EFFORTS,
    OPENROUTER_AGENTIC_UPSTREAM_ID,
)
HOSTED_CONTEXT_POLICY_REVISION = "p4-context-v4"


@dataclass(frozen=True)
class HostedProviderSupportFlags:
    """Fine-grained behavior actually implemented by an endpoint."""

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
    """Current settings for one hosted provider/model implementation."""

    model_provider_id: str
    model_id: str
    model_revision: str
    model_revision_policy: ModelRevisionPolicy
    provider_protocol: str
    provider_api_version: str | None
    endpoint_id: str
    upstream_ids: tuple[str, ...]
    state_mode: str
    context_policy: AgenticContextPolicy
    support_flags: HostedProviderSupportFlags


def hosted_full_context_policy() -> AgenticContextPolicy:
    """Return the common bounded policy declared by the hosted recipes."""
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


def openrouter_full_context_policy() -> AgenticContextPolicy:
    """Use GLM's configured million-token window with Codex-equivalent limits."""
    return AgenticContextPolicy(
        revision="openrouter-full-context-v1",
        max_request_input_tokens=1_000_000,
        context_reserve_tokens=128_000,
        compaction_mode="provider_history",
        compaction_trigger_tokens=750_000,
        max_compacted_state_bytes=1_048_576,
        summary_max_bytes=8_192,
        tool_result_inline_bytes=16_384,
        tool_result_summary_bytes=8_192,
        attachment_projection_mode="workspace_reference",
        steering_delivery_mode="safe_next_turn",
        max_same_turn_steering_messages=0,
    )


GOOGLE_GOVERNED_WORKSPACE_RECIPE = HostedHarnessRecipeManifest(
    model_provider_id="google-ai-studio",
    model_id=GOOGLE_AGENTIC_MODEL_ID,
    model_revision=GOOGLE_AGENTIC_MODEL_REVISION,
    model_revision_policy="exact",
    provider_protocol="google-interactions",
    provider_api_version="v1",
    endpoint_id="google-generativelanguage-v1-interactions",
    upstream_ids=(),
    state_mode="stateless",
    context_policy=hosted_full_context_policy(),
    support_flags=HostedProviderSupportFlags(
        streaming=True,
        usage_accounting=True,
        tool_calling=True,
        supports_empty_tool_catalog=True,
        supports_tool_choice_none=False,
        omits_tools_when_empty=True,
        parallel_tool_calls=True,
        cooperative_cancellation=True,
        continuation_mode="core-managed-stateless-history",
        reasoning_efforts=("high",),
        attachment_modalities=("file",),
        input_token_limit=1_048_576,
        output_token_limit=65_536,
    ),
)


OPENROUTER_GOVERNED_WORKSPACE_RECIPE = HostedHarnessRecipeManifest(
    model_provider_id="openrouter",
    model_id=OPENROUTER_AGENTIC_MODEL_ID,
    model_revision=OPENROUTER_AGENTIC_MODEL_REVISION,
    model_revision_policy="provider_alias",
    provider_protocol="openrouter-chat-completions",
    provider_api_version="v1",
    endpoint_id="openrouter-chat-completions-v1",
    upstream_ids=(OPENROUTER_AGENTIC_UPSTREAM_ID,),
    state_mode="client-managed-history",
    context_policy=openrouter_full_context_policy(),
    support_flags=HostedProviderSupportFlags(
        streaming=True,
        usage_accounting=True,
        tool_calling=True,
        supports_empty_tool_catalog=True,
        supports_tool_choice_none=True,
        omits_tools_when_empty=True,
        parallel_tool_calls=True,
        cooperative_cancellation=True,
        continuation_mode="core-managed-chat-history",
        reasoning_efforts=OPENROUTER_AGENTIC_REASONING_EFFORTS,
        attachment_modalities=("file",),
        input_token_limit=1_048_576,
        output_token_limit=131_072,
    ),
)


__all__ = [
    "GOOGLE_GOVERNED_WORKSPACE_RECIPE",
    "HOSTED_CONTEXT_POLICY_REVISION",
    "HostedHarnessRecipeManifest",
    "HostedProviderSupportFlags",
    "OPENROUTER_GOVERNED_WORKSPACE_RECIPE",
    "hosted_full_context_policy",
    "openrouter_full_context_policy",
]
