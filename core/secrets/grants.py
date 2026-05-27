"""Secret grant lifecycle helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import re
from uuid import uuid4

from core.secrets.errors import SecretBindingError
from core.secrets.models import SecretGrantRecord
from core.secrets.secret_bindings import LOGICAL_NAME_PATTERN, SECRET_REF_PATTERN
from core.secrets.store import SecretStore
from core.secrets.target_policy import (
    assert_target_patterns_safe_for_actions,
    has_explicit_target_patterns,
    normalize_target_patterns_or_wildcard,
)


ACTION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,126}$")
RESOURCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,126}$")
TARGET_OPTIONAL_ACTIONS = {"app.backend"}


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def _normalize_actions(actions: list[str] | None) -> list[str]:
    normalized = []
    for action in actions or []:
        candidate = str(action).strip().lower()
        if not ACTION_PATTERN.fullmatch(candidate):
            raise SecretBindingError(f"Secret grant actions must be stable lowercase identifiers, got `{action}`.")
        if candidate not in normalized:
            normalized.append(candidate)
    if not normalized:
        raise SecretBindingError("Secret grants require at least one action.")
    return normalized


def build_secret_grant(
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
    """Build one app-scoped grant for controlled secret use."""
    normalized_logical_name = str(logical_name).strip().lower()
    if not LOGICAL_NAME_PATTERN.fullmatch(normalized_logical_name):
        raise SecretBindingError(f"Logical secret names must be lowercase and stable, got `{logical_name}`.")
    normalized_ref = str(secret_ref).strip().lower()
    if not SECRET_REF_PATTERN.fullmatch(normalized_ref):
        raise SecretBindingError("Secret grants must use canonical platform secret refs.")
    timestamp = now or utcnow()
    normalized_actions = _normalize_actions(actions)
    normalized_resource_type = _normalize_resource_segment(resource_type, field="resource_type")
    normalized_resource_id = _normalize_resource_segment(resource_id, field="resource_id")
    if bool(normalized_resource_type) != bool(normalized_resource_id):
        raise SecretBindingError("Secret grants must provide both resource_type and resource_id, or neither.")
    if not has_explicit_target_patterns(target_patterns) and any(action not in TARGET_OPTIONAL_ACTIONS for action in normalized_actions):
        raise SecretBindingError("Secret grants for external or user-directed actions require explicit target patterns.")
    normalized_targets = normalize_target_patterns_or_wildcard(target_patterns)
    assert_target_patterns_safe_for_actions(normalized_actions, normalized_targets)
    return SecretGrantRecord(
        grant_id=grant_id or f"grant:{workspace_id}:{app_id}:{normalized_logical_name}:{uuid4()}",
        workspace_id=str(workspace_id).strip(),
        app_id=str(app_id).strip(),
        secret_ref=normalized_ref,
        logical_name=normalized_logical_name,
        actions=normalized_actions,
        target_patterns=normalized_targets,
        status="active",
        created_at=timestamp,
        updated_at=timestamp,
        expires_at=expires_at,
        created_by_user_id=created_by_user_id,
        reason=str(reason).strip() or None if reason is not None else None,
        resource_type=normalized_resource_type,
        resource_id=normalized_resource_id,
    )


def create_secret_grant(store: SecretStore, **kwargs) -> SecretGrantRecord:
    """Persist one active app-scoped grant."""
    return store.save_secret_grant(build_secret_grant(**kwargs))


def _normalize_resource_segment(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    if not RESOURCE_PATTERN.fullmatch(normalized):
        raise SecretBindingError(f"Secret grant {field} must be a stable lowercase identifier.")
    return normalized


def revoke_secret_grant(
    store: SecretStore,
    *,
    grant_id: str,
    now: datetime | None = None,
) -> SecretGrantRecord:
    """Revoke one secret grant without deleting its audit-relevant metadata."""
    grant = store.get_secret_grant(grant_id)
    return store.save_secret_grant(replace(grant, status="revoked", updated_at=now or utcnow()))
