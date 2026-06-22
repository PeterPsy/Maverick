"""Redaction-safe credential authorization checks for provider routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from core.providers.errors import ProviderDisabledError
from core.providers.models import ProviderCredentialRequirement, ProviderDefinition
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.store import ProviderStore
from core.secrets.errors import SecretPolicyError
from core.secrets.models import SecretBindingRecord, SecretGrantRecord, SecretResolutionContext
from core.secrets.policy import assert_grant_allows_context
from core.secrets.store import SecretStore


@dataclass(frozen=True)
class ProviderCredentialAuthorization:
    """Redaction-safe summary of whether provider credentials are authorized."""

    provider_id: str
    workspace_id: str
    required: bool
    authorized: bool
    secret_alias_or_logical_name: str | None
    provider_credential_binding_id_optional: str | None = None
    provider_secret_binding_id_optional: str | None = None
    app_secret_grant_id_optional: str | None = None
    reason_codes: list[str] = field(default_factory=list)


def provider_secret_target(provider_id: str, mode: str) -> str:
    """Return the stable grant target used for app-mediated provider secret use."""
    return f"maverick://providers/{provider_id}/{mode}"


def check_provider_credential_authorization(
    provider_store: ProviderStore,
    *,
    definition: ProviderDefinition,
    workspace_id: str,
    secret_store: SecretStore | None = None,
    app_id: str | None = None,
    action: str = "provider.hosted_text.execute",
    target: str | None = None,
    now: datetime | None = None,
) -> ProviderCredentialAuthorization:
    """Return whether a provider has credential authorization without reading secret values."""
    requirement = _primary_requirement(definition)
    secret_name = _requirement_name(requirement)
    if not definition.requires_credentials and requirement is None:
        return ProviderCredentialAuthorization(
            provider_id=definition.provider_id,
            workspace_id=workspace_id,
            required=False,
            authorized=True,
            secret_alias_or_logical_name=None,
            reason_codes=["provider_credentials_not_required"],
        )

    reason_codes = ["credential_requirement_declared"]
    if requirement is None:
        reason_codes.append("credential_requirement_defaulted")
    scope = requirement.secret_binding_scope if requirement is not None else "provider"
    default_target = target or provider_secret_target(definition.provider_id, "plain_hosted_chat")

    if scope in {"provider", "provider_or_app"}:
        try:
            binding = resolve_provider_binding(
                provider_store,
                provider_id=definition.provider_id,
                workspace_id=workspace_id,
            )
        except ProviderDisabledError:
            return ProviderCredentialAuthorization(
                provider_id=definition.provider_id,
                workspace_id=workspace_id,
                required=True,
                authorized=False,
                secret_alias_or_logical_name=secret_name,
                reason_codes=[*reason_codes, "provider_credential_binding_disabled"],
            )
        if binding is not None:
            return ProviderCredentialAuthorization(
                provider_id=definition.provider_id,
                workspace_id=workspace_id,
                required=True,
                authorized=True,
                secret_alias_or_logical_name=secret_name,
                provider_credential_binding_id_optional=binding.binding_id,
                reason_codes=[*reason_codes, "provider_credential_binding_present"],
            )
        secret_binding = _find_provider_secret_binding(
            secret_store,
            provider_id=definition.provider_id,
            workspace_id=workspace_id,
            logical_name=secret_name,
        )
        if secret_binding is not None:
            return ProviderCredentialAuthorization(
                provider_id=definition.provider_id,
                workspace_id=workspace_id,
                required=True,
                authorized=True,
                secret_alias_or_logical_name=secret_name,
                provider_secret_binding_id_optional=secret_binding.binding_id,
                reason_codes=[*reason_codes, "provider_secret_binding_present"],
            )
        reason_codes.append("provider_credential_binding_missing")

    if scope in {"app", "provider_or_app"} and app_id and secret_store is not None:
        grant = _find_app_secret_grant(
            secret_store,
            workspace_id=workspace_id,
            app_id=app_id,
            logical_name=secret_name,
            action=action,
            target=default_target,
            now=now,
        )
        if grant is not None:
            return ProviderCredentialAuthorization(
                provider_id=definition.provider_id,
                workspace_id=workspace_id,
                required=True,
                authorized=True,
                secret_alias_or_logical_name=secret_name,
                app_secret_grant_id_optional=grant.grant_id,
                reason_codes=[*reason_codes, "app_secret_grant_present"],
            )
        reason_codes.append("app_secret_grant_missing")

    return ProviderCredentialAuthorization(
        provider_id=definition.provider_id,
        workspace_id=workspace_id,
        required=True,
        authorized=False,
        secret_alias_or_logical_name=secret_name,
        reason_codes=reason_codes,
    )


def _primary_requirement(definition: ProviderDefinition) -> ProviderCredentialRequirement | None:
    return definition.credential_requirements[0] if definition.credential_requirements else None


def _requirement_name(requirement: ProviderCredentialRequirement | None) -> str:
    return requirement.secret_alias_or_logical_name if requirement is not None else "default"


def _find_provider_secret_binding(
    secret_store: SecretStore | None,
    *,
    provider_id: str,
    workspace_id: str,
    logical_name: str,
) -> SecretBindingRecord | None:
    if secret_store is None:
        return None
    bindings = secret_store.list_secret_bindings(
        provider_id=provider_id,
        scope="provider",
        logical_name=logical_name,
    )
    for binding in bindings:
        if binding.status == "active" and binding.workspace_id in {workspace_id, None}:
            return binding
    return None


def _find_app_secret_grant(
    secret_store: SecretStore,
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    action: str,
    target: str,
    now: datetime | None,
) -> SecretGrantRecord | None:
    context = SecretResolutionContext(
        workspace_id=workspace_id,
        app_id=app_id,
        action=action,
        target=target,
    )
    for grant in secret_store.list_secret_grants(workspace_id=workspace_id, app_id=app_id, status="active"):
        if grant.logical_name != logical_name:
            continue
        try:
            assert_grant_allows_context(grant, context, now=now)
        except SecretPolicyError:
            continue
        return grant
    return None
