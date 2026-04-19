"""Identity-domain services."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from dataclasses import replace
import hashlib
import hmac
import secrets

from core.identity.models import (
    AccountType,
    AuthSessionRecord,
    PasswordCredentialRecord,
    PlatformRole,
    UserRecord,
)
from core.identity.errors import UserNotFoundError
from core.identity.store import IdentityStore
from core.workspaces.service import ensure_workspace_membership, get_active_workspace_for_user, set_active_workspace_for_user
from core.workspaces.store import WorkspaceStore


PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 210_000


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


def hash_password(password: str, *, salt: str | None = None, iterations: int = PASSWORD_ITERATIONS) -> str:
    """Hash one password using the core's deterministic storage envelope."""
    active_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), active_salt.encode("utf-8"), iterations)
    return f"{PASSWORD_ALGORITHM}${iterations}${active_salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify one plaintext password against a stored hash envelope."""
    try:
        algorithm, iterations_text, salt, expected = password_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        candidate = hash_password(password, salt=salt, iterations=int(iterations_text)).rsplit("$", 1)[-1]
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


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


def register_user(store: IdentityStore, record: UserRecord, credential: PasswordCredentialRecord) -> UserRecord:
    """Persist a new user and its password credential."""
    store.save_user(record)
    store.save_password_credential(credential)
    return record


def bootstrap_default_admin(
    identity_store: IdentityStore,
    workspace_store: WorkspaceStore,
    *,
    username: str,
    password: str,
    now: datetime | None = None,
) -> UserRecord:
    """Ensure the installation has one admin user for the hosted shell."""
    timestamp = now or utcnow()
    try:
        user = identity_store.get_user_by_username(username)
    except UserNotFoundError:
        user = build_user_record(
            user_id=f"user:{username}",
            username=username,
            display_name="Maverick Admin",
            platform_role="admin",
            now=timestamp,
        )
        credential = build_password_credential(
            user_id=user.user_id,
            password_hash=hash_password(password),
            algorithm=PASSWORD_ALGORITHM,
            now=timestamp,
        )
        register_user(identity_store, user, credential)

    ensure_workspace_membership(
        workspace_store,
        membership_id=f"default:{user.user_id}",
        workspace_id="default",
        user_id=user.user_id,
        role="admin",
        now=timestamp,
    )
    if get_active_workspace_for_user(workspace_store, user_id=user.user_id) is None:
        set_active_workspace_for_user(workspace_store, user_id=user.user_id, workspace_id="default", now=timestamp)
    return user


def authenticate_password(identity_store: IdentityStore, *, username: str, password: str) -> UserRecord:
    """Authenticate one active user with password credentials."""
    user = identity_store.get_user_by_username(username)
    if not user.is_active:
        raise UserNotFoundError(f"User `{username}` is not active.")
    credential = identity_store.get_password_credential(user.user_id)
    if credential.algorithm != PASSWORD_ALGORITHM or not verify_password(password, credential.password_hash):
        raise UserNotFoundError(f"Invalid credentials for `{username}`.")
    return user


def touch_auth_session(
    identity_store: IdentityStore,
    *,
    session: AuthSessionRecord,
    now: datetime | None = None,
) -> AuthSessionRecord:
    """Update session activity without changing its identity."""
    timestamp = now or utcnow()
    updated = replace(session, last_seen_at=timestamp, updated_at=timestamp)
    return identity_store.save_auth_session(updated)


def revoke_auth_session(
    identity_store: IdentityStore,
    *,
    session: AuthSessionRecord,
    now: datetime | None = None,
) -> AuthSessionRecord:
    """Revoke one auth session."""
    timestamp = now or utcnow()
    updated = replace(session, status="revoked", updated_at=timestamp)
    return identity_store.save_auth_session(updated)


def session_expiry(*, now: datetime | None = None, days: int = 7) -> datetime:
    """Return the default auth-session expiry timestamp."""
    return (now or utcnow()) + timedelta(days=days)
