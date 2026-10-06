"""Bounded renewal of existing login sessions without changing their identity."""

from datetime import datetime, timedelta

from core.identity.models import AuthSessionRecord
from core.identity.store import IdentityStore

SESSION_IDLE_DAYS = 30
SESSION_ABSOLUTE_DAYS = 90
SESSION_RENEWAL_INTERVAL = timedelta(days=1)


def renew_auth_session(store: IdentityStore, session: AuthSessionRecord, *, now: datetime) -> AuthSessionRecord:
    """Extend a live session conditionally; revocation and deletion always win."""
    if session.status != "active" or session.expires_at <= now:
        return session
    expiry = min(now + timedelta(days=SESSION_IDLE_DAYS), session.created_at + timedelta(days=SESSION_ABSOLUTE_DAYS))
    if expiry < session.expires_at or expiry - session.expires_at >= SESSION_RENEWAL_INTERVAL:
        store.extend_auth_session(session, expires_at=expiry, now=now)
    # A concurrent password reset/logout must never be overwritten or hidden.
    return store.get_auth_session(session.session_id)
