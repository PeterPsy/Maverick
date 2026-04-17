"""Identity-domain services."""

from __future__ import annotations

from datetime import UTC, datetime

from core.identity.models import (
    AccountType,
    AuthSessionRecord,
    PasswordCredentialRecord,
    PlatformRole,
    UserRecord,
)
from core.identity.store import MongoIdentityStore


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def build_user_record(
    *,
    user_id: str,
    username: str,
    email: str | None = None,
    display_name: str | None = None,
    account_type: AccountType = "standard",
    platform_role: PlatformRole = "member",
    is_active: bool = True,
    now: datetime | None = None,
) -> UserRecord:
    """Build a canonical identity user record."""
    timestamp = now or utcnow()
    return UserRecord(
        user_id=user_id,
        username=username,
        email=email,
        display_name=display_name,
        account_type=account_type,
        platform_role=platform_role,
        is_active=is_active,
        created_at=timestamp,
        updated_at=timestamp,
    )


def build_password_credential(*, user_id: str, password_hash: str, algorithm: str, now: datetime | None = None) -> PasswordCredentialRecord:
    """Build a stored password credential record."""
    return PasswordCredentialRecord(
        user_id=user_id,
        password_hash=password_hash,
        algorithm=algorithm,
        updated_at=now or utcnow(),
    )


def build_auth_session(
    *,
    session_id: str,
    user_id: str,
    expires_at: datetime,
    now: datetime | None = None,
) -> AuthSessionRecord:
    """Build a new active authentication session."""
    timestamp = now or utcnow()
    return AuthSessionRecord(
        session_id=session_id,
        user_id=user_id,
        status="active",
        expires_at=expires_at,
        last_seen_at=None,
        created_at=timestamp,
        updated_at=timestamp,
    )


def register_user(store: MongoIdentityStore, record: UserRecord, credential: PasswordCredentialRecord) -> UserRecord:
    """Persist a new user and its password credential."""
    store.save_user(record)
    store.save_password_credential(credential)
    return record
