"""HTTP session and authentication API for the hosted platform shell."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from core.api.http import StartResponse, json_response, read_json_body, request_cookies
from core.api.platform_state import PlatformState
from core.identity.errors import SessionNotFoundError, UserNotFoundError
from core.identity.models import AuthSessionRecord, UserRecord
from core.identity.service import (
    authenticate_password,
    build_auth_session,
    revoke_auth_session,
    session_expiry,
    touch_auth_session,
)
from core.workspaces.service import resolve_active_workspace_for_user


SESSION_COOKIE = "maverick_session"


@dataclass(frozen=True)
class RequestSession:
    """Authenticated user context derived from one HTTP request."""

    user: UserRecord
    session: AuthSessionRecord
    workspace_id: str


def _now() -> datetime:
    return datetime.now(tz=UTC)


def session_cookie_header(session_id: str, *, expires_at: datetime | None = None, secure: bool = False) -> tuple[str, str]:
    """Build the Set-Cookie header for an auth session."""
    parts = [f"{SESSION_COOKIE}={session_id}", "Path=/", "HttpOnly", "SameSite=Lax"]
    if secure:
        parts.append("Secure")
    if expires_at is not None:
        parts.append(f"Expires={expires_at.strftime('%a, %d %b %Y %H:%M:%S GMT')}")
    return ("Set-Cookie", "; ".join(parts))


def clear_session_cookie_header(*, secure: bool = False) -> tuple[str, str]:
    """Build a Set-Cookie header that removes the auth cookie."""
    secure_part = "; Secure" if secure else ""
    return ("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax{secure_part}; Max-Age=0")


def resolve_request_session(state: PlatformState, environ: dict) -> RequestSession | None:
    """Resolve the request's active session, if one exists and is valid."""
    session_id = request_cookies(environ).get(SESSION_COOKIE)
    if not session_id:
        return None
    try:
        session = state.identity_store.get_auth_session(session_id)
    except SessionNotFoundError:
        return None
    now = _now()
    if session.status != "active" or session.expires_at <= now:
        return None
    try:
        user = state.identity_store.get_user(session.user_id)
    except UserNotFoundError:
        return None
    if not user.is_active:
        return None
    touch_auth_session(state.identity_store, session=session, now=now)
    selection = resolve_active_workspace_for_user(state.workspace_store, user_id=user.user_id, now=now)
    if selection is None:
        return None
    workspace_id = selection.workspace_id
    return RequestSession(user=user, session=session, workspace_id=workspace_id)


def public_user_payload(user: UserRecord) -> dict[str, object]:
    """Return safe user fields for shell APIs."""
    return {
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "account_type": user.account_type,
        "platform_role": user.platform_role,
    }


def session_payload(context: RequestSession | None) -> dict[str, object]:
    """Return the public session payload consumed by base-shell."""
    if context is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user": public_user_payload(context.user),
        "workspace_id": context.workspace_id,
        "expires_at": context.session.expires_at,
    }


def require_session(state: PlatformState, environ: dict, start_response: StartResponse) -> RequestSession | list[bytes]:
    """Return an authenticated context or a 401 response."""
    context = resolve_request_session(state, environ)
    if context is None:
        return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
    return context


def handle_session_api(state: PlatformState, environ: dict, start_response: StartResponse) -> list[bytes] | None:
    """Handle auth/session routes, returning None when the path is not owned here."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if path == "/api/session" and method == "GET":
        return json_response(start_response, session_payload(resolve_request_session(state, environ)))
    if path == "/api/auth/login" and method == "POST":
        body = read_json_body(environ)
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        try:
            user = authenticate_password(state.identity_store, username=username, password=password)
        except UserNotFoundError:
            return json_response(start_response, {"error": "invalid_credentials"}, status="401 Unauthorized")
        expires_at = session_expiry()
        session = state.identity_store.save_auth_session(
            build_auth_session(session_id=str(uuid4()), user_id=user.user_id, expires_at=expires_at)
        )
        selection = resolve_active_workspace_for_user(state.workspace_store, user_id=user.user_id, now=_now())
        if selection is None:
            return json_response(start_response, {"error": "workspace_not_available"}, status="403 Forbidden")
        workspace_id = selection.workspace_id
        context = RequestSession(user=user, session=session, workspace_id=workspace_id)
        return json_response(
            start_response,
            session_payload(context),
            headers=[session_cookie_header(session.session_id, expires_at=expires_at, secure=_request_is_https(environ))],
        )
    if path == "/api/auth/logout" and method == "POST":
        context = resolve_request_session(state, environ)
        if context is not None:
            state.sidecar_browser_sessions.revoke_actor(context.user.user_id)
            revoke_auth_session(state.identity_store, session=context.session)
        return json_response(start_response, {"authenticated": False}, headers=[clear_session_cookie_header(secure=_request_is_https(environ))])
    return None


def _request_is_https(environ: dict) -> bool:
    return str(environ.get("wsgi.url_scheme") or "").lower() == "https" or str(environ.get("HTTP_X_FORWARDED_PROTO") or "").lower() == "https"
