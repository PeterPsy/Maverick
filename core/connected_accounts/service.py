"""Federated login, explicit account linking, consent and account ownership."""

import base64
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import os
import secrets
from urllib.parse import urlencode

from core.connected_accounts import google
from core.app_sdk.google_profile import google_picture_url
from core.connected_accounts.google_identity import verify_identity
from core.connected_accounts.models import AccountSelection, ConnectedAccount, OAuthFlow
from core.identity.service import build_user_record
from core.secrets.service import build_secret_ref, create_platform_secret, rotate_platform_secret, revoke_platform_secret
from core.workspaces.service import resolve_active_workspace_for_user
from core.workspaces.errors import WorkspaceMembershipError


def digest(value):
    return sha256(value.encode()).hexdigest()


def public_account(account):
    return {"account_id": account.account_id, "provider": account.provider,
            "email": account.email, "display_name": account.display_name,
            "picture_url": google_picture_url(account.picture_url),
            "status": account.status, "services": google.available_services(account.scopes)}


def authorization_url(state, flow, raw_state, browser):
    client_id, _ = google.credentials(state.secret_store)
    scopes = {"openid", "email", "profile"}
    for service in flow.services:
        scopes.update(google.SERVICES[service]["scopes"])
    query = {"client_id": client_id, "redirect_uri": flow.redirect_uri, "response_type": "code",
             "scope": " ".join(sorted(scopes)), "state": raw_state, "nonce": digest(browser),
             "code_challenge": base64.urlsafe_b64encode(sha256(browser.encode()).digest()).decode().rstrip("="),
             "code_challenge_method": "S256", "include_granted_scopes": "true"}
    if flow.services:
        query.update(access_type="offline", prompt="consent")
    else:
        query["prompt"] = "select_account"
    return google.AUTH_URL + "?" + urlencode(query)


def start_flow(state, *, mode, services, context=None, now=None, transport="browser"):
    timestamp = now or datetime.now(UTC)
    selected_services = google.validate_services(services)
    if not isinstance(mode, str) or mode not in {"login", "connect"} or (mode == "connect" and context is None):
        raise google.AccountError("authentication_required", status=401)
    if not isinstance(transport, str) or transport not in {"browser", "system-browser"}:
        raise google.AccountError("invalid_google_transport")
    google.credentials(state.secret_store)
    redirect = google.redirect_uri()
    browser = secrets.token_urlsafe(48)
    raw_state = secrets.token_urlsafe(32)
    flow = OAuthFlow(digest(raw_state), digest(browser), mode,
                     context.user.user_id if context else None,
                     context.workspace_id if context else None,
                     digest(context.session.session_id) if context else None,
                     selected_services, redirect, "pending", timestamp + timedelta(minutes=10))
    if transport == "system-browser":
        handoff = secrets.token_urlsafe(48)
        flow = replace(flow, status="awaiting_browser", initiator_hash=digest(browser), handoff_hash=digest(handoff))
        state.account_store.save_flow(flow)
        # Neither handoff authority nor OAuth state is sent in URL query logs.
        origin = redirect.removesuffix(google.CALLBACK_PATH)
        return {"browser_url": origin + "/?google_handoff=1#" + raw_state + "." + handoff,
                "flow_id": flow.state_hash}, browser
    state.account_store.save_flow(flow)
    return {"authorization_url": authorization_url(state, flow, raw_state, browser)}, browser


def complete_flow(state, *, raw_state, browser, code, context=None, now=None,
                  exchange=None, identity_verifier=None):
    timestamp = now or datetime.now(UTC)
    flow = state.account_store.consume_flow(digest(raw_state), digest(browser), timestamp)
    if not flow:
        raise google.AccountError("google_flow_invalid")
    return complete_claimed_flow(state, flow=flow, browser=browser, code=code, context=context,
                                 now=timestamp, exchange=exchange, identity_verifier=identity_verifier)


def complete_claimed_flow(state, *, flow, browser, code, context=None, now=None,
                          exchange=None, identity_verifier=None):
    """Process a flow already atomically consumed by this Core request."""
    timestamp = now or datetime.now(UTC)
    if flow.mode == "connect" and (context is None or context.user.user_id != flow.user_id
            or context.workspace_id != flow.workspace_id or digest(context.session.session_id) != flow.session_generation):
        raise google.AccountError("google_flow_session_changed", status=403)
    client_id, client_secret = google.credentials(state.secret_store)
    tokens = (exchange or google.json_request)(google.TOKEN_URL, data={
        "client_id": client_id, "client_secret": client_secret, "code": code,
        "code_verifier": browser, "redirect_uri": flow.redirect_uri, "grant_type": "authorization_code",
    })
    claims = (identity_verifier or verify_identity)(tokens.get("id_token"), client_id=client_id,
                                                    nonce=flow.browser_hash, now=timestamp.timestamp())
    existing = state.account_store.find_subject("google", claims["sub"])
    if flow.mode == "connect":
        user = context.user
        if existing and existing.user_id != user.user_id:
            raise google.AccountError("google_account_already_linked", status=409)
    elif existing:
        user = state.identity_store.get_user(existing.user_id)
    else:
        # An email match is not proof that an existing Maverick identity may be
        # taken over. That user must sign in locally and explicitly link Google.
        if any((item.email or "").casefold() == claims["email"].casefold() for item in state.identity_store.list_users()):
            raise google.AccountError("google_account_link_required", status=403)
        if os.environ.get("MAVERICK_GOOGLE_ALLOW_REGISTRATION", "1") != "1":
            raise google.AccountError("google_registration_disabled", status=403)
        username = "google_" + digest(claims["sub"])[:24]
        user = build_user_record(user_id="user:" + username, username=username,
                                 email=claims["email"], display_name=claims.get("name"), now=timestamp)
        state.identity_store.save_user(user)
    if not user.is_active:
        raise google.AccountError("google_user_inactive", status=403)
    account_id = "google_" + digest(claims["sub"])[:32]
    token_scopes = str(tokens.get("scope") or "").split()
    refresh_token = str(tokens.get("refresh_token") or "")
    secret_ref = existing.secret_ref if existing and existing.status == "connected" else None
    if refresh_token:
        if secret_ref:
            secret_id = secret_ref.rsplit("/", 1)[-1]
            rotate_platform_secret(state.secret_store, secret_id=secret_id, raw_value=refresh_token, now=timestamp)
        else:
            secret = create_platform_secret(state.secret_store, label="Google account credential",
                                            raw_value=refresh_token, secret_id="google-account-" + secrets.token_hex(16), now=timestamp)
            secret_ref = build_secret_ref(secret_id=secret.secret_id)
    elif secret_ref and existing:
        token_scopes = sorted(set(token_scopes) | set(existing.scopes))
    if google.available_services(token_scopes) and not secret_ref:
        raise google.AccountError("google_offline_consent_required")
    account = ConnectedAccount(account_id, "google", claims["sub"], user.user_id, claims["email"],
                               str(claims.get("name") or claims["email"]), sorted(set(token_scopes)),
                               secret_ref, "connected", existing.created_at if existing else timestamp, timestamp,
                               google_picture_url(claims.get("picture")))
    account = state.account_store.claim_account(account)
    # Service accounts never supply the Maverick identity photo, including its first photo.
    avatar = google_picture_url(claims.get("picture"))
    if avatar and flow.mode == "login":
        user = state.identity_store.update_user_avatar(user.user_id, avatar, now=timestamp)
    selection = resolve_active_workspace_for_user(state.workspace_store, user_id=user.user_id, now=timestamp)
    if selection:
        select_account(state, user_id=user.user_id, workspace_id=selection.workspace_id, account_id=account.account_id)
    return user, account, flow.mode, selection


def owned_account(state, user_id, account_id):
    account = state.account_store.get_account(account_id)
    if account is None or account.user_id != user_id:
        raise google.AccountError("account_not_found", status=404)
    return account


def select_account(state, *, user_id, workspace_id, account_id):
    account = owned_account(state, user_id, account_id)
    _require_membership(state, user_id, workspace_id)
    if account.status != "connected":
        raise google.AccountError("google_reconnect_required", status=409)
    def update(current):
        account_ids = list(dict.fromkeys([*(current.account_ids if current else []), account_id]))
        return AccountSelection(digest(user_id + "\0" + workspace_id), user_id,
            workspace_id, account_id, current.disabled_apps if current else [], account_ids)
    return state.account_store.update_selection(user_id, workspace_id, update)


def set_workspace_account_access(state, *, user_id, workspace_id, account_id, enabled):
    account = owned_account(state, user_id, account_id)
    _require_membership(state, user_id, workspace_id)
    if not isinstance(enabled, bool):
        raise google.AccountError("invalid_account_access")
    if enabled and account.status != "connected":
        raise google.AccountError("google_reconnect_required", status=409)
    def update(current):
        account_ids = list(current.account_ids if current else [])
        if enabled and account_id not in account_ids:
            account_ids.append(account_id)
        elif not enabled:
            account_ids = [item for item in account_ids if item != account_id]
        default = current.account_id if current and current.account_id in account_ids else next(iter(account_ids), "")
        return AccountSelection(digest(user_id + "\0" + workspace_id), user_id,
            workspace_id, default, current.disabled_apps if current else [], account_ids)
    return state.account_store.update_selection(user_id, workspace_id, update)


def _require_membership(state, user_id, workspace_id):
    try:
        membership = state.workspace_store.get_membership(user_id=user_id, workspace_id=workspace_id)
    except WorkspaceMembershipError:
        raise google.AccountError("workspace_access_required", status=403) from None
    if membership.status != "active" or not state.identity_store.get_user(user_id).is_active:
        raise google.AccountError("workspace_access_required", status=403)


def disconnect_account(state, *, user_id, account_id):
    account = owned_account(state, user_id, account_id)
    # Withdraw local authority before contacting Google. A provider outage must
    # never leave a disconnected account usable by another app invocation.
    state.account_store.save_account(replace(account, status="disconnected", updated_at=datetime.now(UTC)))
    revoked_at_google = False
    if account.secret_ref:
        try:
            token = google.secret_value(state.secret_store, account.secret_ref)
            status, _, _ = google.provider_request(google.Request(google.REVOKE_URL,
                data=urlencode({"token": token}).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"}))
            revoked_at_google = status < 400
        except (google.AccountError, google.SecretError):
            pass
        revoke_platform_secret(state.secret_store, secret_id=account.secret_ref.rsplit("/", 1)[-1])
    return {"status": "disconnected", "revoked_at_google": revoked_at_google}
