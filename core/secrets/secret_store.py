"""Secret metadata and raw-value lifecycle helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import re
import unicodedata

from core.secrets.errors import SecretBindingError
from core.secrets.models import SecretRecord
from core.secrets.store import SecretStore


SECRET_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,126}$")


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def _normalize_name(value: str, *, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.strip().lower()).strip("-")
    return slug or fallback


def _validate_name(value: str, *, label: str) -> str:
    normalized = str(value).strip().lower()
    if not SECRET_NAME_PATTERN.fullmatch(normalized):
        raise SecretBindingError(f"{label} must be lowercase and stable, got `{value}`.")
    return normalized


def build_secret_ref(*, secret_id: str | None = None, alias: str | None = None) -> str:
    """Build one canonical secret reference."""
    if alias is not None:
        return f"platform:secret-alias/{_validate_name(alias, label='Secret alias')}"
    if secret_id is None:
        raise SecretBindingError("A secret ref requires either `secret_id` or `alias`.")
    return f"platform:secrets/{_validate_name(secret_id, label='Secret id')}"


def build_secret_record(
    *,
    label: str,
    alias: str | None = None,
    description: str | None = None,
    secret_id: str | None = None,
    now: datetime | None = None,
) -> SecretRecord:
    """Build one platform-owned secret metadata record."""
    timestamp = now or utcnow()
    normalized_secret_id = _validate_name(secret_id or _normalize_name(label, fallback="secret"), label="Secret id")
    normalized_alias = None if alias is None else _validate_name(alias, label="Secret alias")
    return SecretRecord(
        secret_id=normalized_secret_id,
        alias=normalized_alias,
        label=str(label).strip(),
        description=str(description).strip() or None if description is not None else None,
        status="active",
        created_at=timestamp,
        updated_at=timestamp,
    )


def create_secret(
    store: SecretStore,
    *,
    label: str,
    raw_value: str,
    alias: str | None = None,
    description: str | None = None,
    secret_id: str | None = None,
    now: datetime | None = None,
) -> SecretRecord:
    """Persist one secret metadata record and its raw value."""
    record = build_secret_record(
        label=label,
        alias=alias,
        description=description,
        secret_id=secret_id,
        now=now,
    )
    if not raw_value:
        raise SecretBindingError("Secret raw values must not be empty.")
    store.save_secret(record)
    store.save_secret_value(secret_id=record.secret_id, raw_value=raw_value)
    return record


def rotate_secret_value(store: SecretStore, *, secret_id: str, raw_value: str, now: datetime | None = None) -> SecretRecord:
    """Rotate one secret raw value without changing the secret identity."""
    if not raw_value:
        raise SecretBindingError("Secret raw values must not be empty.")
    record = store.get_secret(secret_id)
    updated = replace(record, updated_at=now or utcnow(), status="active")
    store.save_secret(updated)
    store.save_secret_value(secret_id=secret_id, raw_value=raw_value)
    return updated


def disable_secret(store: SecretStore, *, secret_id: str, now: datetime | None = None) -> SecretRecord:
    """Disable one secret while preserving its stored raw value."""
    record = store.get_secret(secret_id)
    updated = replace(record, status="disabled", updated_at=now or utcnow())
    return store.save_secret(updated)


def revoke_secret(store: SecretStore, *, secret_id: str, now: datetime | None = None) -> SecretRecord:
    """Revoke one secret and remove its persisted raw value."""
    record = store.get_secret(secret_id)
    updated = replace(record, status="revoked", updated_at=now or utcnow())
    store.save_secret(updated)
    store.delete_secret_value(secret_id=secret_id)
    return updated
