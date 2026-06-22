"""Deterministic provider routing for model and runtime profiles."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

from core.providers.errors import ProviderError
from core.providers.models import (
    ProviderDefinition,
    ProviderModelOption,
    RoutingDecision,
    WorkspaceProviderPolicy,
)
from core.providers.provider_authorization import check_provider_credential_authorization
from core.providers.provider_registry import ProviderRegistry
from core.providers.provider_selection import ProviderSelectionService
from core.providers.store import ProviderStore
from core.secrets.store import SecretStore


@dataclass(frozen=True)
class ProviderRoutingContext:
    """Inputs used to produce one redaction-safe routing decision."""

    workspace_id: str
    provider_store: ProviderStore
    registry: ProviderRegistry
    secret_store: SecretStore | None = None
    policy: WorkspaceProviderPolicy | None = None
    request_id: str | None = None
    user_tier: str | None = None
    app_id: str | None = None
    allow_fallback_codex: bool = False
    requested_capabilities: list[str] | None = None


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def select_provider_for_profile(profile: str, context: ProviderRoutingContext) -> RoutingDecision:
    """Return a deterministic, redaction-safe routing decision for one profile."""
    normalized_profile = str(profile).strip()
    if normalized_profile == "plain_hosted_chat":
        decision = _select_fast_model(context)
        return replace(
            decision,
            profile="plain_hosted_chat",
            reason_codes=[*decision.reason_codes, "plain_hosted_chat_profile_uses_fast_model"],
        )
    if normalized_profile == "fast_model":
        return _select_fast_model(context)
    if normalized_profile == "heavy_runtime":
        return _select_heavy_runtime(context)
    return _decision(
        context,
        profile=normalized_profile,
        requested_capabilities=context.requested_capabilities or [],
        candidate_provider_ids=[],
        selected_provider_id=None,
        selected_model_id_or_voice_id=None,
        selected_runtime_engine_id=None,
        execution_path=None,
        credential_authorization_required=False,
        provider_credential_binding_id_optional=None,
        provider_secret_binding_id_optional=None,
        app_secret_grant_id_optional=None,
        fallback_used=False,
        reason_codes=["routing_profile_unknown"],
    )


def primary_routing_failure_reason(decision: RoutingDecision) -> str:
    """Return the stable primary failure reason for an unsuccessful decision."""
    if decision.execution_path is not None and (
        decision.selected_provider_id is not None or decision.selected_runtime_engine_id is not None
    ):
        return "provider_routing_succeeded"
    reason_codes = list(decision.reason_codes)
    if any(
        code in reason_codes
        for code in (
            "provider_credential_binding_missing",
            "provider_credential_binding_disabled",
            "provider_credential_binding_invalid_secret_ref",
            "provider_secret_binding_present_but_unusable",
            "app_secret_grant_missing",
            "fallback_no_credential_authorization",
        )
    ):
        return "provider_credential_authorization_missing"
    if any(code.startswith("provider_disabled:") for code in reason_codes):
        return "provider_disabled"
    if any(code.startswith("workspace_policy_denied_model:") for code in reason_codes):
        return "provider_model_unavailable"
    if any(code.startswith("workspace_policy_denied:") for code in reason_codes):
        return "workspace_policy_denied"
    if "routing_profile_unknown" in reason_codes:
        return "routing_profile_unknown"
    if reason_codes:
        return reason_codes[-1]
    return "no_fast_model_available"


def _select_fast_model(context: ProviderRoutingContext) -> RoutingDecision:
    requested_capabilities = context.requested_capabilities or ["text_generation", "low_latency"]
    candidates = _fast_model_candidates(context.registry.list_provider_definitions())
    candidate_ids = [candidate.provider_id for candidate in candidates]
    reason_codes = ["routing_profile_fast_model"]
    policy = _policy_for_context(context)

    for candidate in candidates:
        model = _select_model(candidate, policy=policy, user_tier=context.user_tier)
        if candidate.status != "active":
            reason_codes.append(f"provider_disabled:{candidate.provider_id}")
            continue
        if not _provider_allowed(candidate.provider_id, policy=policy, user_tier=context.user_tier):
            reason_codes.append(f"workspace_policy_denied:{candidate.provider_id}")
            continue
        if model is None:
            reason_codes.append(f"workspace_policy_denied_model:{candidate.provider_id}")
            continue

        authorization = check_provider_credential_authorization(
            context.provider_store,
            definition=candidate,
            workspace_id=context.workspace_id,
            secret_store=context.secret_store,
            app_id=context.app_id,
        )
        reason_codes.extend(authorization.reason_codes)
        if not authorization.authorized:
            reason_codes.append("fallback_no_credential_authorization")
            continue

        return _decision(
            context,
            profile="fast_model",
            requested_capabilities=requested_capabilities,
            candidate_provider_ids=candidate_ids,
            selected_provider_id=candidate.provider_id,
            selected_model_id_or_voice_id=model.model_id,
            selected_runtime_engine_id=None,
            execution_path="plain_hosted_text",
            credential_authorization_required=authorization.required,
            provider_credential_binding_id_optional=authorization.provider_credential_binding_id_optional,
            provider_secret_binding_id_optional=authorization.provider_secret_binding_id_optional,
            app_secret_grant_id_optional=authorization.app_secret_grant_id_optional,
            fallback_used=False,
            reason_codes=[
                *reason_codes,
                "workspace_policy_allowed",
                "plain_hosted_text_selected",
            ],
        )

    if context.allow_fallback_codex or policy.fallback_rules.get("fallback_codex_explicit", False):
        return _decision(
            context,
            profile="fast_model",
            requested_capabilities=requested_capabilities,
            candidate_provider_ids=candidate_ids,
            selected_provider_id=None,
            selected_model_id_or_voice_id=None,
            selected_runtime_engine_id="codex",
            execution_path="agentic_runtime",
            credential_authorization_required=False,
            provider_credential_binding_id_optional=None,
            provider_secret_binding_id_optional=None,
            app_secret_grant_id_optional=None,
            fallback_used=True,
            reason_codes=[*reason_codes, "fallback_codex_explicit", "runtime_engine_remains_codex"],
        )

    return _decision(
        context,
        profile="fast_model",
        requested_capabilities=requested_capabilities,
        candidate_provider_ids=candidate_ids,
        selected_provider_id=None,
        selected_model_id_or_voice_id=None,
        selected_runtime_engine_id=None,
        execution_path=None,
        credential_authorization_required=any(candidate.requires_credentials for candidate in candidates),
        provider_credential_binding_id_optional=None,
        provider_secret_binding_id_optional=None,
        app_secret_grant_id_optional=None,
        fallback_used=False,
        reason_codes=[*reason_codes, "no_fast_model_available"],
    )


def _select_heavy_runtime(context: ProviderRoutingContext) -> RoutingDecision:
    reason_codes = ["routing_profile_heavy_runtime"]
    try:
        definition, selection = ProviderSelectionService(context.provider_store, context.registry).resolve_runtime_backend_provider(
            workspace_id=context.workspace_id
        )
    except ProviderError as error:
        return _decision(
            context,
            profile="heavy_runtime",
            requested_capabilities=context.requested_capabilities or ["interactive_runtime", "tools"],
            candidate_provider_ids=[],
            selected_provider_id=None,
            selected_model_id_or_voice_id=None,
            selected_runtime_engine_id=None,
            execution_path=None,
            credential_authorization_required=False,
            provider_credential_binding_id_optional=None,
            provider_secret_binding_id_optional=None,
            app_secret_grant_id_optional=None,
            fallback_used=False,
            reason_codes=[*reason_codes, str(error)],
        )
    return _decision(
        context,
        profile="heavy_runtime",
        requested_capabilities=context.requested_capabilities or ["interactive_runtime", "tools"],
        candidate_provider_ids=[definition.provider_id],
        selected_provider_id=definition.provider_id,
        selected_model_id_or_voice_id=selection.model_id if selection is not None else None,
        selected_runtime_engine_id=definition.provider_id,
        execution_path="agentic_runtime",
        credential_authorization_required=definition.requires_credentials,
        provider_credential_binding_id_optional=selection.binding_id if selection is not None else None,
        provider_secret_binding_id_optional=None,
        app_secret_grant_id_optional=None,
        fallback_used=False,
        reason_codes=[*reason_codes, "runtime_engine_remains_codex"],
    )


def _fast_model_candidates(definitions: list[ProviderDefinition]) -> list[ProviderDefinition]:
    candidates = [
        definition
        for definition in definitions
        if definition.provider_role == "model_provider"
        and "text" in definition.capabilities.input_modalities
        and "text" in definition.capabilities.output_modalities
        and definition.capabilities.latency_class == "low"
        and definition.execution_contract is not None
        and definition.execution_contract.adapter_type == "hosted_text_generation"
    ]
    return sorted(candidates, key=lambda definition: definition.provider_id)


def _select_model(
    definition: ProviderDefinition,
    *,
    policy: WorkspaceProviderPolicy,
    user_tier: str | None,
) -> ProviderModelOption | None:
    models = list(definition.model_options)
    if not models:
        return None
    allowed_model_ids = _allowed_model_ids(policy, user_tier=user_tier)
    if allowed_model_ids:
        models = [model for model in models if model.model_id in allowed_model_ids]
    if not models:
        return None
    for model in models:
        if model.model_id == definition.default_model_family:
            return model
    return models[0]


def _provider_allowed(provider_id: str, *, policy: WorkspaceProviderPolicy, user_tier: str | None) -> bool:
    allowed = _allowed_provider_ids(policy, user_tier=user_tier)
    return not allowed or provider_id in allowed


def _allowed_provider_ids(policy: WorkspaceProviderPolicy, *, user_tier: str | None) -> set[str]:
    allowed = set(policy.allowed_provider_ids)
    tier_rule = _tier_rule(policy, user_tier)
    allowed.update(tier_rule.get("allowed_provider_ids", []))
    return allowed


def _allowed_model_ids(policy: WorkspaceProviderPolicy, *, user_tier: str | None) -> set[str]:
    allowed = set(policy.allowed_model_ids)
    tier_rule = _tier_rule(policy, user_tier)
    allowed.update(tier_rule.get("allowed_model_ids", []))
    return allowed


def _tier_rule(policy: WorkspaceProviderPolicy, user_tier: str | None) -> dict[str, list[str]]:
    if not user_tier:
        return {}
    rule = policy.plan_or_tier_rules.get(user_tier, {})
    return rule if isinstance(rule, dict) else {}


def _policy_for_context(context: ProviderRoutingContext) -> WorkspaceProviderPolicy:
    if context.policy is not None:
        return context.policy
    return WorkspaceProviderPolicy(workspace_id=context.workspace_id)


def _decision(
    context: ProviderRoutingContext,
    *,
    profile: str,
    requested_capabilities: list[str],
    candidate_provider_ids: list[str],
    selected_provider_id: str | None,
    selected_model_id_or_voice_id: str | None,
    selected_runtime_engine_id: str | None,
    execution_path: str | None,
    credential_authorization_required: bool,
    provider_credential_binding_id_optional: str | None,
    provider_secret_binding_id_optional: str | None,
    app_secret_grant_id_optional: str | None,
    fallback_used: bool,
    reason_codes: list[str],
) -> RoutingDecision:
    policy = _policy_for_context(context)
    return RoutingDecision(
        request_id=context.request_id or str(uuid4()),
        workspace_id=context.workspace_id,
        profile=profile,
        requested_capabilities=requested_capabilities,
        candidate_provider_ids=candidate_provider_ids,
        selected_provider_id=selected_provider_id,
        selected_model_id_or_voice_id=selected_model_id_or_voice_id,
        selected_runtime_engine_id=selected_runtime_engine_id,
        execution_path=execution_path,
        policy_id_or_version=policy.policy_id_or_version,
        credential_authorization_required=credential_authorization_required,
        provider_credential_binding_id_optional=provider_credential_binding_id_optional,
        provider_secret_binding_id_optional=provider_secret_binding_id_optional,
        app_secret_grant_id_optional=app_secret_grant_id_optional,
        fallback_used=fallback_used,
        reason_codes=_dedupe(reason_codes),
        created_at=utcnow(),
    )


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
