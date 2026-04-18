"""Controlled secret resolution for runtime use."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from core.secrets.errors import SecretPolicyError, SecretResolutionError
from core.secrets.models import ResolvedSecretLease, SecretBindingRecord, SecretRef, SecretResolutionContext
from core.secrets.store import SecretStore


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def parse_secret_ref(secret_ref: str) -> SecretRef:
    """Parse one canonical secret reference."""
    normalized = str(secret_ref).strip().lower()
    if normalized.startswith("platform:secrets/"):
        return SecretRef(raw_ref=normalized, kind="secret_id", value=normalized.removeprefix("platform:secrets/"))
    if normalized.startswith("platform:secret-alias/"):
        return SecretRef(raw_ref=normalized, kind="alias", value=normalized.removeprefix("platform:secret-alias/"))
    raise SecretResolutionError(f"Unsupported secret ref `{secret_ref}`.")


def redact_secret_value(raw_value: str) -> str:
    """Return one operator-safe redacted secret preview."""
    if len(raw_value) <= 4:
        return "*" * len(raw_value)
    return f"{raw_value[:2]}***{raw_value[-2:]}"


def _assert_binding_allowed(binding: SecretBindingRecord, context: SecretResolutionContext) -> None:
    if binding.status != "active":
        raise SecretPolicyError(f"Secret binding `{binding.binding_id}` is not active.")
    if binding.scope == "workspace":
        if binding.workspace_id != context.workspace_id:
            raise SecretPolicyError("Workspace secret binding cannot be used outside its workspace.")
        return
    if binding.scope == "app":
        if binding.workspace_id != context.workspace_id or binding.app_id != context.app_id:
            raise SecretPolicyError("App secret binding cannot be used outside its app workspace scope.")
        return
    if binding.scope == "provider":
        if binding.workspace_id is not None and binding.workspace_id != context.workspace_id:
            raise SecretPolicyError("Provider secret binding cannot be used outside its workspace scope.")
        if binding.provider_id != context.provider_id:
            raise SecretPolicyError("Provider secret binding cannot be used for a different provider.")
        return
    raise SecretPolicyError(f"Unsupported secret binding scope `{binding.scope}`.")


def _resolve_secret_id(store: SecretStore, secret_ref: SecretRef) -> str:
    if secret_ref.kind == "secret_id":
        return store.get_secret(secret_ref.value).secret_id
    return store.get_secret_by_alias(secret_ref.value).secret_id


def resolve_secret_for_runtime(
    store: SecretStore,
    *,
    context: SecretResolutionContext,
    secret_ref: str | None = None,
    binding_id: str | None = None,
) -> ResolvedSecretLease:
    """Resolve one secret value under one runtime authorization context."""
    source_binding: SecretBindingRecord | None = None
    if binding_id is not None:
        source_binding = store.get_secret_binding(binding_id)
        _assert_binding_allowed(source_binding, context)
        normalized_ref = source_binding.secret_ref
    elif secret_ref is not None and context.allow_unbound_secret_refs and (context.operator_request or context.platform_delivery):
        normalized_ref = str(secret_ref).strip().lower()
    else:
        raise SecretPolicyError("Runtime secret resolution requires one authorized binding or an operator-approved direct ref.")

    parsed_ref = parse_secret_ref(normalized_ref)
    secret_id = _resolve_secret_id(store, parsed_ref)
    secret_record = store.get_secret(secret_id)
    if secret_record.status != "active":
        raise SecretPolicyError(f"Secret `{secret_record.secret_id}` is not active.")
    raw_value = store.get_secret_value(secret_id=secret_record.secret_id)
    return ResolvedSecretLease(
        lease_id=str(uuid4()),
        secret_id=secret_record.secret_id,
        secret_ref=normalized_ref,
        source_binding_id=None if source_binding is None else source_binding.binding_id,
        value=raw_value,
        redacted_value=redact_secret_value(raw_value),
        issued_at=utcnow(),
    )
