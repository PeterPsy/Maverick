"""Secret binding helpers for workspace, app, and provider use."""

from __future__ import annotations

from datetime import UTC, datetime
import re

from core.secrets.errors import SecretBindingError
from core.secrets.models import SecretBindingRecord, SecretBindingScope
from core.secrets.store import SecretStore


LOGICAL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,126}$")
SECRET_REF_PATTERN = re.compile(r"^platform:(secrets|secret-alias)/[a-z0-9][a-z0-9._-]{1,126}$")


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def _normalize_logical_name(value: str) -> str:
    normalized = str(value).strip().lower()
    if not LOGICAL_NAME_PATTERN.fullmatch(normalized):
        raise SecretBindingError(f"Logical secret names must be lowercase and stable, got `{value}`.")
    return normalized


def _normalize_secret_ref(secret_ref: str) -> str:
    normalized = str(secret_ref).strip().lower()
    if not SECRET_REF_PATTERN.fullmatch(normalized):
        raise SecretBindingError(
            "Secret bindings must use canonical refs such as `platform:secrets/openai` or `platform:secret-alias/default-openai`."
        )
    return normalized


def build_secret_binding(
    *,
    scope: SecretBindingScope,
    logical_name: str,
    secret_ref: str,
    binding_id: str | None = None,
    workspace_id: str | None = None,
    app_id: str | None = None,
    provider_id: str | None = None,
    now: datetime | None = None,
) -> SecretBindingRecord:
    """Build one secret binding record for one consumer scope."""
    timestamp = now or utcnow()
    normalized_name = _normalize_logical_name(logical_name)
    normalized_ref = _normalize_secret_ref(secret_ref)
    if scope == "workspace" and workspace_id is None:
        raise SecretBindingError("Workspace secret bindings require `workspace_id`.")
    if scope == "app" and (workspace_id is None or app_id is None):
        raise SecretBindingError("App secret bindings require `workspace_id` and `app_id`.")
    if scope == "provider" and provider_id is None:
        raise SecretBindingError("Provider secret bindings require `provider_id`.")
    return SecretBindingRecord(
        binding_id=binding_id or f"{scope}:{workspace_id or 'platform'}:{app_id or provider_id or normalized_name}",
        scope=scope,
        workspace_id=workspace_id,
        app_id=app_id,
        provider_id=provider_id,
        secret_ref=normalized_ref,
        logical_name=normalized_name,
        status="active",
        created_at=timestamp,
        updated_at=timestamp,
    )


def bind_secret(
    store: SecretStore,
    *,
    scope: SecretBindingScope,
    logical_name: str,
    secret_ref: str,
    binding_id: str | None = None,
    workspace_id: str | None = None,
    app_id: str | None = None,
    provider_id: str | None = None,
    now: datetime | None = None,
) -> SecretBindingRecord:
    """Persist one secret binding for one consumer scope."""
    record = build_secret_binding(
        scope=scope,
        logical_name=logical_name,
        secret_ref=secret_ref,
        binding_id=binding_id,
        workspace_id=workspace_id,
        app_id=app_id,
        provider_id=provider_id,
        now=now,
    )
    return store.save_secret_binding(record)


def resolve_active_binding(
    store: SecretStore,
    *,
    scope: SecretBindingScope,
    logical_name: str,
    workspace_id: str | None = None,
    app_id: str | None = None,
    provider_id: str | None = None,
) -> SecretBindingRecord | None:
    """Resolve one active secret binding for the given scope and logical name."""
    bindings = [
        binding
        for binding in store.list_secret_bindings(
            workspace_id=workspace_id,
            app_id=app_id,
            provider_id=provider_id,
            scope=scope,
            logical_name=_normalize_logical_name(logical_name),
        )
        if binding.status == "active"
    ]
    return bindings[0] if bindings else None
