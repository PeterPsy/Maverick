"""Secret metadata and raw-value lifecycle helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import re
from typing import cast
import unicodedata

from core.secrets.errors import SecretBindingError, SecretNotFoundError
from core.secrets.models import SecretKind, SecretRecord
from core.secrets.store import SecretStore


SECRET_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,126}$")
SECRET_KINDS = {"generic", "password", "api_key", "oauth_token", "private_key"}


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


def _validate_kind(value: str) -> SecretKind:
    normalized = str(value).strip().lower()
    if normalized not in SECRET_KINDS:
        raise SecretBindingError(f"Secret kind must be one of {sorted(SECRET_KINDS)}, got `{value}`.")
    return cast(SecretKind, normalized)


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
    kind: SecretKind = "generic",
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
        kind=_validate_kind(kind),
    )


def create_secret(
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
    """Persist one secret metadata record and its raw value."""
    record = build_secret_record(
        label=label,
        alias=alias,
        description=description,
        secret_id=secret_id,
        kind=kind,
        now=now,
    )
    if not raw_value:
        raise SecretBindingError("Secret raw values must not be empty.")
    _assert_secret_identity_available(store, record)
    store.save_secret(record)
    store.save_secret_value(secret_id=record.secret_id, raw_value=raw_value)
    return record


def _assert_secret_identity_available(store: SecretStore, record: SecretRecord) -> None:
    try:
        existing = store.get_secret(record.secret_id)
    except SecretNotFoundError:
        existing = None
    if existing is not None:
        raise SecretBindingError(f"Secret id `{record.secret_id}` already exists; use rotate to change its value.")
    try:
        existing_id_alias = store.get_secret_by_alias(record.secret_id)
    except SecretNotFoundError:
        existing_id_alias = None
    if existing_id_alias is not None:
        raise SecretBindingError(
            f"Secret id `{record.secret_id}` collides with alias on secret `{existing_id_alias.secret_id}`."
        )
    if record.alias is None:
        return
    try:
        existing_alias = store.get_secret_by_alias(record.alias)
    except SecretNotFoundError:
        existing_alias = None
    if existing_alias is not None:
        raise SecretBindingError(
            f"Secret alias `{record.alias}` is already assigned to secret `{existing_alias.secret_id}`; use a unique alias."
        )
    try:
        existing_alias_id = store.get_secret(record.alias)
    except SecretNotFoundError:
        return
    raise SecretBindingError(f"Secret alias `{record.alias}` collides with existing secret id `{existing_alias_id.secret_id}`.")


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
