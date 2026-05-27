"""Secret-domain service facade."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.secrets.errors import SecretBindingError, SecretError
from core.secrets.grants import create_secret_grant, revoke_secret_grant
from core.secrets.models import ResolvedSecretLease, SecretBindingRecord, SecretGrantRecord, SecretKind, SecretRecord, SecretResolutionContext
from core.secrets.secret_bindings import bind_secret, resolve_active_binding
from core.secrets.secret_resolution import parse_secret_ref, resolve_secret_for_app_use, resolve_secret_for_runtime
from core.secrets.secret_store import build_secret_ref, create_secret, disable_secret, revoke_secret, rotate_secret_value, update_secret_metadata
from core.secrets.store import SecretStore


@dataclass(frozen=True)
class SecretLifecycleResult:
    """Secret metadata plus grants revoked as part of the lifecycle change."""

    secret: SecretRecord
    revoked_grants: list[SecretGrantRecord]


def create_platform_secret(
    store: SecretStore,
    *,
    label: str,
    raw_value: str,
    alias: str | None = None,
    description: str | None = None,
    secret_id: str | None = None,
    kind: SecretKind = "generic",
    now: datetime | None = None,
) -> SecretRecord:
    """Create one platform-owned secret."""
    return create_secret(
        store,
        label=label,
        raw_value=raw_value,
        alias=alias,
        description=description,
        secret_id=secret_id,
        kind=kind,
        now=now,
    )


def rotate_platform_secret(
    store: SecretStore,
    *,
    secret_id: str,
    raw_value: str,
    now: datetime | None = None,
) -> SecretRecord:
    """Rotate one platform-owned secret raw value."""
    return rotate_secret_value(store, secret_id=secret_id, raw_value=raw_value, now=now)


def update_platform_secret_metadata(
    store: SecretStore,
    *,
    secret_id: str,
    label: str,
    alias: str | None = None,
    description: str | None = None,
    kind: SecretKind = "generic",
    now: datetime | None = None,
) -> SecretRecord:
    """Update redaction-safe platform secret metadata without reading raw values."""
    return update_secret_metadata(
        store,
        secret_id=secret_id,
        label=label,
        alias=alias,
        description=description,
        kind=kind,
        now=now,
    )


def disable_platform_secret(store: SecretStore, *, secret_id: str, now: datetime | None = None) -> SecretRecord:
    """Disable one platform-owned secret."""
    return disable_platform_secret_with_revocations(store, secret_id=secret_id, now=now).secret


def revoke_platform_secret(store: SecretStore, *, secret_id: str, now: datetime | None = None) -> SecretRecord:
    """Revoke one platform-owned secret and remove its raw value."""
    return revoke_platform_secret_with_revocations(store, secret_id=secret_id, now=now).secret


def disable_platform_secret_with_revocations(
    store: SecretStore,
    *,
    secret_id: str,
    now: datetime | None = None,
) -> SecretLifecycleResult:
    """Disable one platform-owned secret and revoke linked active grants."""
    secret = disable_secret(store, secret_id=secret_id, now=now)
    return SecretLifecycleResult(secret=secret, revoked_grants=revoke_grants_for_secret(store, secret=secret, now=now))


def revoke_platform_secret_with_revocations(
    store: SecretStore,
    *,
    secret_id: str,
    now: datetime | None = None,
) -> SecretLifecycleResult:
    """Revoke one platform-owned secret, delete its value, and revoke linked active grants."""
    secret = revoke_secret(store, secret_id=secret_id, now=now)
    return SecretLifecycleResult(secret=secret, revoked_grants=revoke_grants_for_secret(store, secret=secret, now=now))


def revoke_grants_for_secret(
    store: SecretStore,
    *,
    secret: SecretRecord,
    now: datetime | None = None,
) -> list[SecretGrantRecord]:
    """Revoke active grants linked to one secret id or alias."""
    revoked: list[SecretGrantRecord] = []
    for grant in store.list_secret_grants(status="active"):
        try:
            linked_secret = _secret_for_ref(store, grant.secret_ref)
        except SecretError:
            continue
        if linked_secret.secret_id == secret.secret_id:
            revoked.append(revoke_secret_grant(store, grant_id=grant.grant_id, now=now))
    return revoked


def _secret_for_ref(store: SecretStore, secret_ref: str) -> SecretRecord:
    parsed_ref = parse_secret_ref(secret_ref)
    if parsed_ref.kind == "secret_id":
        return store.get_secret(parsed_ref.value)
    return store.get_secret_by_alias(parsed_ref.value)


def bind_workspace_secret(
    store: SecretStore,
    *,
    workspace_id: str,
    logical_name: str,
    secret_ref: str,
    binding_id: str | None = None,
    now: datetime | None = None,
) -> SecretBindingRecord:
    """Bind one secret ref for one workspace-wide use."""
    return bind_secret(
        store,
        scope="workspace",
        workspace_id=workspace_id,
        logical_name=logical_name,
        secret_ref=secret_ref,
        binding_id=binding_id,
        now=now,
    )


def bind_app_secret(
    store: SecretStore,
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    secret_ref: str,
    binding_id: str | None = None,
    now: datetime | None = None,
) -> SecretBindingRecord:
    """Bind one secret ref for one app inside one workspace."""
    return bind_secret(
        store,
        scope="app",
        workspace_id=workspace_id,
        app_id=app_id,
        logical_name=logical_name,
        secret_ref=secret_ref,
        binding_id=binding_id,
        now=now,
    )


def bind_provider_secret(
    store: SecretStore,
    *,
    provider_id: str,
    logical_name: str,
    secret_ref: str,
    workspace_id: str | None = None,
    binding_id: str | None = None,
    now: datetime | None = None,
) -> SecretBindingRecord:
    """Bind one secret ref for one provider globally or inside one workspace."""
    return bind_secret(
        store,
        scope="provider",
        workspace_id=workspace_id,
        provider_id=provider_id,
        logical_name=logical_name,
        secret_ref=secret_ref,
        binding_id=binding_id,
        now=now,
    )


def resolve_bound_secret(
    store: SecretStore,
    *,
    context: SecretResolutionContext,
    binding_id: str,
) -> ResolvedSecretLease:
    """Resolve one secret through one explicit authorized binding."""
    return resolve_secret_for_runtime(store, context=context, binding_id=binding_id)


def grant_app_secret_use(
    store: SecretStore,
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    secret_ref: str,
    actions: list[str],
    target_patterns: list[str] | None = None,
    grant_id: str | None = None,
    expires_at: datetime | None = None,
    created_by_user_id: str | None = None,
    reason: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    now: datetime | None = None,
) -> SecretGrantRecord:
    """Grant one app controlled use of a secret for scoped actions and targets."""
    return create_secret_grant(
        store,
        workspace_id=workspace_id,
        app_id=app_id,
        logical_name=logical_name,
        secret_ref=secret_ref,
        actions=actions,
        target_patterns=target_patterns,
        grant_id=grant_id,
        expires_at=expires_at,
        created_by_user_id=created_by_user_id,
        reason=reason,
        resource_type=resource_type,
        resource_id=resource_id,
        now=now,
    )


def revoke_app_secret_grant(store: SecretStore, *, grant_id: str, now: datetime | None = None) -> SecretGrantRecord:
    """Revoke one app secret-use grant."""
    return revoke_secret_grant(store, grant_id=grant_id, now=now)


def resolve_app_secret_grant(
    store: SecretStore,
    *,
    workspace_id: str,
    app_id: str,
    grant_id: str,
    action: str,
    target: str | None = None,
    runtime_session_id: str | None = None,
    actor_user_id: str | None = None,
    request_context: dict[str, str] | None = None,
    observability_store=None,
) -> ResolvedSecretLease:
    """Resolve one app secret through an action and target scoped grant."""
    return resolve_secret_for_app_use(
        store,
        context=SecretResolutionContext(
            workspace_id=workspace_id,
            app_id=app_id,
            runtime_session_id=runtime_session_id,
            action=action,
            target=target,
            actor_user_id=actor_user_id,
            request_context=request_context,
        ),
        grant_id=grant_id,
        observability_store=observability_store,
    )


def resolve_workspace_secret(
    store: SecretStore,
    *,
    workspace_id: str,
    logical_name: str,
    runtime_session_id: str | None = None,
) -> ResolvedSecretLease:
    """Resolve one workspace-scoped secret binding."""
    binding = resolve_active_binding(
        store,
        scope="workspace",
        workspace_id=workspace_id,
        logical_name=logical_name,
    )
    if binding is None:
        raise SecretBindingError(f"Workspace secret binding `{logical_name}` was not found in `{workspace_id}`.")
    context = SecretResolutionContext(workspace_id=workspace_id, runtime_session_id=runtime_session_id)
    return resolve_secret_for_runtime(store, context=context, binding_id=binding.binding_id)


def resolve_app_secret(
    store: SecretStore,
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    runtime_session_id: str | None = None,
) -> ResolvedSecretLease:
    """Resolve one app-scoped secret binding."""
    binding = resolve_active_binding(
        store,
        scope="app",
        workspace_id=workspace_id,
        app_id=app_id,
        logical_name=logical_name,
    )
    if binding is None:
        raise SecretBindingError(f"App secret binding `{logical_name}` was not found for `{app_id}` in `{workspace_id}`.")
    context = SecretResolutionContext(
        workspace_id=workspace_id,
        app_id=app_id,
        runtime_session_id=runtime_session_id,
    )
    return resolve_secret_for_runtime(store, context=context, binding_id=binding.binding_id)


def resolve_provider_secret(
    store: SecretStore,
    *,
    provider_id: str,
    workspace_id: str | None = None,
    logical_name: str = "default",
    runtime_session_id: str | None = None,
) -> ResolvedSecretLease:
    """Resolve one provider-scoped secret binding."""
    binding = resolve_active_binding(
        store,
        scope="provider",
        workspace_id=workspace_id,
        provider_id=provider_id,
        logical_name=logical_name,
    )
    if binding is None:
        raise SecretBindingError(f"Provider secret binding `{logical_name}` was not found for `{provider_id}`.")
    context = SecretResolutionContext(
        workspace_id=workspace_id,
        provider_id=provider_id,
        runtime_session_id=runtime_session_id,
    )
    return resolve_secret_for_runtime(store, context=context, binding_id=binding.binding_id)


__all__ = [
    "bind_app_secret",
    "bind_provider_secret",
    "bind_workspace_secret",
    "build_secret_ref",
    "create_platform_secret",
    "disable_platform_secret",
    "grant_app_secret_use",
    "resolve_app_secret_grant",
    "resolve_app_secret",
    "resolve_bound_secret",
    "resolve_provider_secret",
    "resolve_workspace_secret",
    "revoke_platform_secret",
    "revoke_app_secret_grant",
    "rotate_platform_secret",
    "update_platform_secret_metadata",
]
