"""Adapter-independent OAuth identity and connection records."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ConnectedAccount:
    account_id: str
    provider: str
    subject: str
    user_id: str
    email: str
    display_name: str
    scopes: list[str]
    secret_ref: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    picture_url: str = ""
    profile_checked_at: datetime | None = None


@dataclass(frozen=True)
class AccountSelection:
    selection_id: str
    user_id: str
    workspace_id: str
    account_id: str
    disabled_apps: list[str] = field(default_factory=list)
    account_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OAuthFlow:
    state_hash: str
    browser_hash: str
    mode: str
    user_id: str | None
    workspace_id: str | None
    session_generation: str | None
    services: list[str]
    redirect_uri: str
    status: str
    expires_at: datetime
    initiator_hash: str | None = None
    handoff_hash: str | None = None
    result_user_id: str | None = None
    result_workspace_id: str | None = None
    result_error: str | None = None
