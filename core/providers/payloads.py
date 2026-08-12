"""Redaction-safe provider payload helpers for API, CLI, and MCP surfaces."""

from __future__ import annotations

from dataclasses import asdict

from core.providers.models import (
    ProviderDefinition,
    ProviderHostedSelection,
    ProviderModelOption,
    ProviderReasoningOption,
    ProviderSelection,
    ProviderSpeechSelection,
    ProviderSubscriptionUsage,
    ProviderUsageLimit,
    ProviderUsageWindow,
    RoutingDecision,
)


def sort_provider_definitions(definitions: list[ProviderDefinition]) -> list[ProviderDefinition]:
    """Return providers with runtime engines first, then deterministic ids."""
    return sorted(definitions, key=lambda item: (item.provider_role != "runtime_engine", item.provider_id))


def provider_payload(definition: ProviderDefinition) -> dict[str, object]:
    """Return public provider metadata without secret refs or values."""
    return {
        "provider_id": definition.provider_id,
        "label": definition.label,
        "description": definition.description,
        "kind": definition.kind,
        "provider_role": definition.provider_role,
        "status": definition.status,
        "capabilities": asdict(definition.capabilities),
        "default_model_family": definition.default_model_family,
        "model_options": [provider_model_option_payload(option) for option in definition.model_options],
        "requires_credentials": definition.requires_credentials,
        "credential_requirements": [asdict(requirement) for requirement in definition.credential_requirements],
        "network_requirements": [asdict(requirement) for requirement in definition.network_requirements],
        "execution_contract": None if definition.execution_contract is None else asdict(definition.execution_contract),
        "cost_metadata": dict(definition.cost_metadata),
        "latency_metadata": dict(definition.latency_metadata),
        "supported_execution_modes": list(definition.supported_execution_modes),
    }


def provider_reasoning_option_payload(option: ProviderReasoningOption) -> dict[str, object]:
    """Return public reasoning-effort metadata."""
    return {
        "effort": option.effort,
        "label": option.label,
        "description": option.description,
    }


def provider_model_option_payload(option: ProviderModelOption) -> dict[str, object]:
    """Return public provider model metadata."""
    return {
        "model_id": option.model_id,
        "label": option.label,
        "description": option.description,
        "default_reasoning_effort": option.default_reasoning_effort,
        "supported_reasoning_efforts": [
            provider_reasoning_option_payload(reasoning)
            for reasoning in option.supported_reasoning_efforts
        ],
        "input_modalities": list(option.input_modalities),
        "output_modalities": list(option.output_modalities),
        "upstream_provider_options": [dict(item) for item in option.upstream_provider_options],
        "metadata": dict(option.metadata),
    }


def provider_selection_payload(selection: ProviderSelection | None) -> dict[str, object] | None:
    """Return public provider-selection metadata."""
    if selection is None:
        return None
    return {
        "workspace_id": selection.workspace_id,
        "provider_id": selection.provider_id,
        "binding_id": selection.binding_id,
        "selection_scope": selection.selection_scope,
        "selection_reason": selection.selection_reason,
        "updated_at": selection.updated_at,
        "model_id": selection.model_id,
        "model_reasoning_effort": selection.model_reasoning_effort,
    }


def provider_subscription_usage_payload(usage: ProviderSubscriptionUsage) -> dict[str, object]:
    """Return subscription usage without account identifiers or credentials."""
    return {
        "provider_id": usage.provider_id,
        "provider_label": usage.provider_label,
        "available": usage.available,
        "fetched_at": usage.fetched_at.isoformat(),
        "plan_type": usage.plan_type,
        "limits": [provider_usage_limit_payload(limit) for limit in usage.limits],
        "unavailable_reason": usage.unavailable_reason,
        "credits_balance": usage.credits_balance,
        "credits_unlimited": usage.credits_unlimited,
    }


def provider_usage_limit_payload(limit: ProviderUsageLimit) -> dict[str, object]:
    """Return one redaction-safe usage limit."""
    return {
        "limit_id": limit.limit_id,
        "label": limit.label,
        "metered_feature": limit.metered_feature,
        "limit_reached": limit.limit_reached,
        "primary_window": provider_usage_window_payload(limit.primary_window),
        "secondary_window": provider_usage_window_payload(limit.secondary_window),
    }


def provider_usage_window_payload(window: ProviderUsageWindow | None) -> dict[str, object] | None:
    """Return one redaction-safe usage window."""
    if window is None:
        return None
    return {
        "used_percent": window.used_percent,
        "limit_window_seconds": window.limit_window_seconds,
        "reset_after_seconds": window.reset_after_seconds,
        "reset_at_epoch_seconds": window.reset_at_epoch_seconds,
    }


def hosted_provider_selection_payload(selection: ProviderHostedSelection | None) -> dict[str, object] | None:
    """Return public hosted-provider selection metadata."""
    if selection is None:
        return None
    return {
        "workspace_id": selection.workspace_id,
        "profile": selection.profile,
        "provider_id": selection.provider_id,
        "selection_reason": selection.selection_reason,
        "updated_at": selection.updated_at,
        "model_id": selection.model_id,
        "openrouter_provider_routing_by_model": {
            str(model_id): dict(routing)
            for model_id, routing in selection.openrouter_provider_routing_by_model.items()
            if isinstance(routing, dict)
        },
    }


def speech_provider_selection_payload(selection: ProviderSpeechSelection | None) -> dict[str, object] | None:
    """Return public speech-provider selection metadata."""
    if selection is None:
        return None
    return {
        "workspace_id": selection.workspace_id,
        "profile": selection.profile,
        "provider_id": selection.provider_id,
        "selection_reason": selection.selection_reason,
        "updated_at": selection.updated_at,
        "audio_transcription_model_id": selection.audio_transcription_model_id,
        "conversation_model_id": selection.conversation_model_id,
    }


def routing_decision_payload(decision: RoutingDecision) -> dict[str, object]:
    """Return a redaction-safe routing decision payload."""
    payload = asdict(decision)
    payload["created_at"] = decision.created_at.isoformat()
    return payload
