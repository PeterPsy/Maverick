"""Credential-binding helpers for provider-domain records."""

from __future__ import annotations

from datetime import UTC, datetime
import re

from core.observability.service import record_platform_audit, record_platform_event
from core.providers.errors import ProviderCredentialBindingError, ProviderDisabledError
from core.providers.models import ProviderCredentialBinding
from core.providers.store import ProviderStore


SECRET_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9:/._-]{2,127}$")


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def build_provider_credential_binding(
    *,
    binding_id: str | None,
    provider_id: str,
    secret_ref: str,
    workspace_id: str | None = None,
    label: str | None = None,
    status: str = "active",
    now: datetime | None = None,
) -> ProviderCredentialBinding:
    """Build one provider credential binding record."""
    timestamp = now or utcnow()
    normalized_secret_ref = str(secret_ref).strip()
    if not SECRET_REF_PATTERN.fullmatch(normalized_secret_ref):
        raise ProviderCredentialBindingError(
            "Provider secret references must be canonical platform-owned refs such as `platform:providers/codex`."
        )
    return ProviderCredentialBinding(
        binding_id=binding_id or f"{provider_id}:{workspace_id or 'platform'}",
        provider_id=provider_id,
        workspace_id=workspace_id,
        secret_ref=normalized_secret_ref,
        label=str(label or "").strip() or None,
        status="active" if status == "active" else "disabled",
        created_at=timestamp,
        updated_at=timestamp,
    )


def bind_provider_credential(
    store: ProviderStore,
    *,
    provider_id: str,
    secret_ref: str,
    workspace_id: str | None = None,
    label: str | None = None,
    binding_id: str | None = None,
    observability_store=None,
    now: datetime | None = None,
) -> ProviderCredentialBinding:
    """Persist one provider credential binding."""
    record = build_provider_credential_binding(
        binding_id=binding_id,
        provider_id=provider_id,
        secret_ref=secret_ref,
        workspace_id=workspace_id,
        label=label,
        now=now,
    )
    saved = store.save_provider_binding(record)
    if observability_store is not None:
        payload = {"provider_id": provider_id, "workspace_id": workspace_id, "binding_id": saved.binding_id}
        record_platform_audit(
            observability_store,
            action="provider.binding.create",
            status="succeeded",
            source_domain="providers",
            detail=f"Created provider credential binding for `{provider_id}`.",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type="provider.binding.created",
            event_plane="platform",
            source_domain="providers",
            workspace_id=workspace_id,
            provider_id=provider_id,
            payload=payload,
        )
    return saved


def disable_provider_binding(
    store: ProviderStore,
    binding_id: str,
    *,
    observability_store=None,
    now: datetime | None = None,
) -> ProviderCredentialBinding:
    """Mark one provider binding as disabled without deleting its metadata."""
    binding = store.get_provider_binding(binding_id)
    timestamp = now or utcnow()
    updated = ProviderCredentialBinding(
        binding_id=binding.binding_id,
        provider_id=binding.provider_id,
        workspace_id=binding.workspace_id,
        secret_ref=binding.secret_ref,
        label=binding.label,
        status="disabled",
        created_at=binding.created_at,
        updated_at=timestamp,
    )
    saved = store.save_provider_binding(updated)
    if observability_store is not None:
        payload = {"provider_id": saved.provider_id, "workspace_id": saved.workspace_id, "binding_id": saved.binding_id}
        record_platform_audit(
            observability_store,
            action="provider.binding.disable",
            status="succeeded",
            source_domain="providers",
            detail=f"Disabled provider credential binding `{saved.binding_id}`.",
            workspace_id=saved.workspace_id,
            provider_id=saved.provider_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type="provider.binding.disabled",
            event_plane="platform",
            source_domain="providers",
            workspace_id=saved.workspace_id,
            provider_id=saved.provider_id,
            payload=payload,
        )
    return saved


def resolve_provider_binding(
    store: ProviderStore,
    *,
    binding_id: str | None = None,
    provider_id: str,
    workspace_id: str | None = None,
) -> ProviderCredentialBinding | None:
    """Resolve the active provider binding for one provider and optional workspace."""
    if binding_id is not None:
        binding = store.get_provider_binding(binding_id)
        if binding.status != "active":
            raise ProviderDisabledError(f"Provider binding `{binding_id}` is disabled.")
        return binding

    workspace_bindings = [
        binding
        for binding in store.list_provider_bindings(workspace_id=workspace_id, provider_id=provider_id)
        if binding.status == "active"
    ]
    if workspace_bindings:
        return workspace_bindings[0]

    platform_bindings = [
        binding
        for binding in store.list_provider_bindings(provider_id=provider_id)
        if binding.workspace_id is None and binding.status == "active"
    ]
    if platform_bindings:
        return platform_bindings[0]
    return None
