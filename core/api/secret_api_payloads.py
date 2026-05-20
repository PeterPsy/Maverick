"""Payload serializers for the Core Secrets HTTP API."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from core.api.platform_state import PlatformState
from core.observability.models import AuditRecord
from core.secrets.errors import SecretError
from core.secrets.models import SecretGrantRecord, SecretRecord
from core.secrets.secret_resolution import parse_secret_ref


def secret_payload(secret: SecretRecord) -> dict[str, object]:
    """Return Vault-safe secret metadata."""
    return {
        "secret_id": secret.secret_id,
        "alias": secret.alias,
        "label": secret.label,
        "description": secret.description,
        "status": secret.status,
        "kind": secret.kind,
        "created_at": secret.created_at,
        "updated_at": secret.updated_at,
    }


def grant_payload(grant: SecretGrantRecord, *, state: PlatformState | None = None) -> dict[str, object]:
    """Return grant metadata plus derived secret-link state when available."""
    payload = asdict(grant)
    if state is None:
        return payload
    try:
        secret = get_secret_for_ref(state, secret_ref=grant.secret_ref)
        payload["linked_secret_status"] = secret.status
        payload["effective_status"] = _grant_effective_status(grant, linked_secret_status=secret.status)
    except SecretError:
        payload["linked_secret_status"] = "missing"
        payload["effective_status"] = grant.status if grant.status != "active" else "orphaned"
    return payload


def audit_payload(record: AuditRecord) -> dict[str, object]:
    """Return persisted audit metadata."""
    return asdict(record)


def get_secret_for_ref(state: PlatformState, *, secret_ref: str) -> SecretRecord:
    """Resolve one secret ref to metadata without reading the raw value."""
    parsed = parse_secret_ref(secret_ref)
    if parsed.kind == "secret_id":
        return state.secret_store.get_secret(parsed.value)
    return state.secret_store.get_secret_by_alias(parsed.value)


def _grant_effective_status(grant: SecretGrantRecord, *, linked_secret_status: str) -> str:
    if grant.status != "active":
        return grant.status
    if grant.expires_at is not None and grant.expires_at <= datetime.now(tz=UTC):
        return "expired"
    if linked_secret_status != "active":
        return "blocked"
    return "active"
