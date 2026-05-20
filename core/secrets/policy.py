"""Policy checks for controlled secret use."""

from __future__ import annotations

from datetime import UTC, datetime

from core.secrets.errors import SecretPolicyError
from core.secrets.models import SecretGrantRecord, SecretResolutionContext
from core.secrets.target_policy import target_allowed


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def assert_grant_allows_context(
    grant: SecretGrantRecord,
    context: SecretResolutionContext,
    *,
    now: datetime | None = None,
) -> None:
    """Raise when one secret grant does not authorize the requested context."""
    if grant.status != "active":
        raise SecretPolicyError(f"Secret grant `{grant.grant_id}` is not active.")
    if grant.workspace_id != context.workspace_id:
        raise SecretPolicyError("Secret grant cannot be used outside its workspace.")
    if grant.app_id != context.app_id:
        raise SecretPolicyError("Secret grant cannot be used by a different app.")
    if grant.expires_at is not None and grant.expires_at <= (now or utcnow()):
        raise SecretPolicyError(f"Secret grant `{grant.grant_id}` has expired.")
    action = str(context.action or "").strip().lower()
    if not action or action not in grant.actions:
        raise SecretPolicyError("Secret grant does not allow the requested action.")
    target = str(context.target or "").strip()
    if not target_allowed(target, grant.target_patterns):
        raise SecretPolicyError("Secret grant does not allow the requested target.")
