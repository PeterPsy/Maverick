"""One-use OAuth handoff between a native webview and the system browser.

Google callbacks remain bound to their own browser cookie and PKCE verifier.
Only the original webview's HttpOnly cookie can collect the resulting login.
"""

from dataclasses import replace
from datetime import UTC, datetime
import hmac
import secrets

from core.connected_accounts.google import AccountError
from core.connected_accounts.service import authorization_url, digest


def live_flow(state, flow_id):
    flow = state.account_store.get_flow(str(flow_id or ""))
    if not flow or flow.expires_at <= datetime.now(UTC):
        raise AccountError("google_flow_invalid")
    return flow


def matches_context(flow, context):
    return (context is not None and context.user.user_id == flow.user_id
            and context.workspace_id == flow.workspace_id
            and hmac.compare_digest(digest(context.session.session_id), flow.session_generation or ""))


def launch(state, *, raw_state, handoff, resolve_context):
    flow = live_flow(state, digest(str(raw_state or "")))
    if (flow.status != "awaiting_browser" or not flow.initiator_hash or not flow.handoff_hash
            or not hmac.compare_digest(digest(str(handoff or "")), flow.handoff_hash)):
        raise AccountError("google_flow_invalid")
    context = resolve_context(flow)
    if flow.mode == "connect" and not matches_context(flow, context):
        raise AccountError("google_flow_session_changed", status=403)
    browser = secrets.token_urlsafe(48)
    updated = replace(flow, browser_hash=digest(browser), handoff_hash=None, status="pending")
    target = authorization_url(state, updated, raw_state, browser)
    if not state.account_store.transition_flow(updated, "awaiting_browser"):
        raise AccountError("google_flow_invalid")
    return {"authorization_url": target}, browser


def finish(state, flow, *, user_id=None, workspace_id=None, error=None):
    if flow.initiator_hash:
        state.account_store.transition_flow(replace(flow, status="completed", handoff_hash=None,
            result_user_id=user_id, result_workspace_id=workspace_id, result_error=error), "consumed")


def collect(state, *, flow_id, browser, context, cancel=False):
    flow = live_flow(state, flow_id)
    if not flow.initiator_hash or not hmac.compare_digest(flow.initiator_hash, digest(browser)):
        raise AccountError("google_flow_invalid")
    if flow.mode == "connect" and not matches_context(flow, context):
        raise AccountError("google_flow_session_changed", status=403)
    if flow.mode == "login" and ((flow.session_generation and not matches_context(flow, context))
            or (not flow.session_generation and context is not None)):
        raise AccountError("google_flow_session_changed", status=403)
    if cancel and flow.status in {"awaiting_browser", "pending"}:
        if state.account_store.transition_flow(replace(flow, status="cancelled", handoff_hash=None), flow.status):
            return {"status": "cancelled"}, None
    if flow.status in {"awaiting_browser", "pending", "consumed"}:
        return {"status": "pending"}, None
    if flow.status != "completed":
        raise AccountError("google_flow_invalid")
    if not state.account_store.transition_flow(replace(flow, status="delivered"), "completed"):
        raise AccountError("google_flow_invalid")
    if flow.result_error:
        return {"status": "failed", "error": flow.result_error}, None
    user = state.identity_store.get_user(flow.result_user_id)
    from core.workspaces.service import resolve_active_workspace_for_user
    selection = resolve_active_workspace_for_user(state.workspace_store, user_id=user.user_id)
    if not user.is_active or selection is None or selection.workspace_id != flow.result_workspace_id:
        raise AccountError("google_flow_session_changed", status=403)
    return {"status": "completed"}, user if flow.mode == "login" else None
