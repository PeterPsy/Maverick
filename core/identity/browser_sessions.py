"""Bounded browser login delegated by a trusted app invocation."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import os
from urllib.parse import urlsplit
from uuid import uuid4

from core.identity.models import AuthSessionRecord
from core.identity.session_lifecycle import SESSION_ABSOLUTE_DAYS
from core.identity.errors import SessionNotFoundError, UserNotFoundError
from core.identity.service import revoke_auth_session
from core.runtime.errors import RuntimeSessionNotFoundError
from core.workspaces.service import resolve_active_workspace_for_user


BROWSER_SESSION_TTL = timedelta(hours=4)


def platform_browser_origin() -> str:
    """Use the configured platform origin, including named local app-frame hosts."""
    origin = os.environ.get("MAVERICK_SIDECAR_PLATFORM_ORIGIN", "").strip().rstrip("/")
    if not origin:
        api = urlsplit(os.environ.get("MAVERICK_API_BASE", "http://127.0.0.1:8014"))
        port = api.port or int(os.environ.get("MAVERICK_PORT", "8014"))
        origin = f"http://maverick.localhost:{port}"
    parsed = urlsplit(origin)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.path or parsed.query or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname != "maverick.localhost")):
        raise ValueError("platform_browser_origin_invalid")
    return origin


def is_browser_session(session: AuthSessionRecord) -> bool:
    return any((session.browser_workspace_id, session.browser_origin,
                session.browser_runtime_session_id, session.browser_login_generation))


def _login_generation(identity_store, user_id: str, now: datetime) -> str | None:
    sessions = [session.session_id for session in identity_store.list_auth_sessions_for_user(user_id)
                if not is_browser_session(session) and session.status == "active"
                and session.expires_at > now
                and session.created_at + timedelta(days=SESSION_ABSOLUTE_DAYS) > now]
    return sha256("\0".join(sorted(sessions)).encode()).hexdigest() if sessions else None


def browser_session_is_current(identity_store, workspace_store, runtime_store,
                               session: AuthSessionRecord, *, origin: str | None = None,
                               now: datetime | None = None) -> bool:
    """Recheck the actor, login generation, workspace and originating runtime."""
    timestamp = now or datetime.now(UTC)
    if (not all((session.browser_workspace_id, session.browser_origin,
                 session.browser_runtime_session_id, session.browser_login_generation))
            or session.status != "active" or session.expires_at <= timestamp
            or session.expires_at > session.created_at + BROWSER_SESSION_TTL
            or (origin is not None and origin != session.browser_origin)):
        return False
    if _login_generation(identity_store, session.user_id, timestamp) != session.browser_login_generation:
        return False
    try:
        runtime = runtime_store.get_session(session.browser_runtime_session_id)
        user = identity_store.get_user(session.user_id)
    except (RuntimeSessionNotFoundError, UserNotFoundError):
        return False
    if (not user.is_active or runtime.owner_user_id != user.user_id
            or runtime.workspace_id != session.browser_workspace_id
            or runtime.ended_at is not None or runtime.status != "running"):
        return False
    selection = resolve_active_workspace_for_user(workspace_store, user_id=user.user_id, now=timestamp)
    return selection is not None and selection.workspace_id == session.browser_workspace_id


def issue_platform_browser_session(identity_store, workspace_store, runtime_store,
                                   *, user_id: str, workspace_id: str,
                                   runtime_session_id: str, now: datetime | None = None) -> dict:
    """Return a private cookie descriptor; never return it as a tool result."""
    timestamp = now or datetime.now(UTC)
    session = AuthSessionRecord(
        session_id=str(uuid4()), user_id=user_id, status="active",
        expires_at=timestamp + BROWSER_SESSION_TTL, last_seen_at=timestamp,
        created_at=timestamp, updated_at=timestamp,
        browser_workspace_id=workspace_id, browser_origin=platform_browser_origin(),
        browser_runtime_session_id=runtime_session_id,
        browser_login_generation=_login_generation(identity_store, user_id, timestamp),
    )
    if not browser_session_is_current(identity_store, workspace_store, runtime_store, session, now=timestamp):
        raise ValueError("platform_browser_authentication_unavailable")
    identity_store.save_auth_session(session)
    frame_domain = os.environ.get("MAVERICK_SIDECAR_INSTALLATION_DOMAIN", "").strip().lower().rstrip(".")
    frame_suffix = f".sidecars.{frame_domain or urlsplit(session.browser_origin).hostname}"
    return {"origin": session.browser_origin, "cookie_name": "maverick_session",
            "cookie_value": session.session_id, "expires_at": session.expires_at.timestamp(),
            "user_id": user_id, "workspace_id": workspace_id, "frame_host_suffix": frame_suffix}


def revoke_platform_browser_session(identity_store, session_id: str) -> None:
    """Discard a failed delegation without masking concurrent password reset."""
    try:
        session = identity_store.get_auth_session(session_id)
    except SessionNotFoundError:
        return
    revoke_auth_session(identity_store, session=session)
