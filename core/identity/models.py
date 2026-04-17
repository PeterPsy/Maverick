"""Identity-domain records for the Maverick v3 control plane."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


AccountType = Literal["standard", "facilitated"]
PlatformRole = Literal["admin", "member"]
SessionStatus = Literal["active", "revoked", "expired"]


@dataclass(frozen=True)
class UserRecord:
    """Canonical user record owned by the identity domain."""

    user_id: str
    username: str
    email: str | None
    display_name: str | None
    account_type: AccountType
    platform_role: PlatformRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PasswordCredentialRecord:
    """Stored password credential metadata for one user."""

    user_id: str
    password_hash: str
    algorithm: str
    updated_at: datetime


@dataclass(frozen=True)
class AuthSessionRecord:
    """Authentication session metadata for one signed-in user."""

    session_id: str
    user_id: str
    status: SessionStatus
    expires_at: datetime
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime
