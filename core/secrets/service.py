"""Secret-domain service facade."""

from __future__ import annotations

from datetime import datetime

from core.secrets.errors import SecretBindingError
from core.secrets.models import ResolvedSecretLease, SecretBindingRecord, SecretRecord, SecretResolutionContext
from core.secrets.secret_bindings import bind_secret, resolve_active_binding
from core.secrets.secret_resolution import resolve_secret_for_runtime
from core.secrets.secret_store import build_secret_ref, create_secret, disable_secret, revoke_secret, rotate_secret_value
from core.secrets.store import SecretStore


def create_platform_secret(
    store: SecretStore,
    *,
    label: str,
    raw_value: str,
    alias: str | None = None,
    description: str | None = None,
    secret_id: str | None = None,
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


def disable_platform_secret(store: SecretStore, *, secret_id: str, now: datetime | None = None) -> SecretRecord:
    """Disable one platform-owned secret."""
    return disable_secret(store, secret_id=secret_id, now=now)


def revoke_platform_secret(store: SecretStore, *, secret_id: str, now: datetime | None = None) -> SecretRecord:
    """Revoke one platform-owned secret and remove its raw value."""
    return revoke_secret(store, secret_id=secret_id, now=now)


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
    "resolve_app_secret",
    "resolve_bound_secret",
    "resolve_provider_secret",
    "resolve_workspace_secret",
    "revoke_platform_secret",
    "rotate_platform_secret",
]
