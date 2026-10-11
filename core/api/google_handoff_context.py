"""Recover native OAuth's initiating authority through canonical session checks."""

import hmac

from core.api.session_api import SESSION_COOKIE, resolve_request_session
from core.connected_accounts.browser_handoff import matches_context
from core.connected_accounts.google import AccountError
from core.connected_accounts.service import digest


def source_context(state, flow, environ):
    if flow.mode != "connect":
        return None
    # Flow records retain only a session hash. A session is recovered internally
    # from that owner's sessions; its raw ID never crosses the native boundary.
    for session in state.identity_store.list_auth_sessions_for_user(flow.user_id):
        if hmac.compare_digest(digest(session.session_id), flow.session_generation or ""):
            context = resolve_request_session(state, {**environ, "HTTP_COOKIE": f"{SESSION_COOKIE}={session.session_id}"})
            if matches_context(flow, context):
                return context
            break
    raise AccountError("google_flow_session_changed", status=403)
