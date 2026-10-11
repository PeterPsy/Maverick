"""Top-level Google login and personal connected-account management routes."""

from dataclasses import replace
from datetime import UTC, datetime
import os
from urllib.parse import urlsplit
from uuid import uuid4
from types import SimpleNamespace

from core.api.http import json_response, query_params, read_json_body, request_cookies, status_line
from core.api.session_api import resolve_request_session, session_cookie_header, _request_is_https
from core.connected_accounts import google
from core.connected_accounts.service import complete_flow, digest, disconnect_account, public_account, select_account, start_flow
from core.identity.errors import UserNotFoundError
from core.identity.service import build_auth_session, session_expiry
from core.secrets.errors import SecretError
from core.secrets.secret_resolution import parse_secret_ref

FLOW_COOKIE = "maverick_google_flow"


def _flow_cookie(value, *, secure, clear=False):
    return ("Set-Cookie", f"{FLOW_COOKIE}={value}; Path=/api/auth/google; HttpOnly; SameSite=Lax; Max-Age={0 if clear else 600}" + ("; Secure" if secure else ""))


def _redirect(start_response, target, headers=None):
    start_response("303 See Other", [("Location", target), ("Cache-Control", "no-store"),
                                    ("Referrer-Policy", "no-referrer"), ("Content-Length", "0"), *(headers or [])])
    return [b""]


def provider_status(state):
    configured = state.account_store is not None
    try:
        google.redirect_uri()
        for ref in google.credential_refs():
            parsed_ref = parse_secret_ref(ref)
            secret = state.secret_store.get_secret_by_alias(parsed_ref.value) if parsed_ref.kind == "alias" else state.secret_store.get_secret(parsed_ref.value)
            configured = configured and secret.status == "active"
    except (google.AccountError, SecretError, ValueError):
        configured = False
    return {"configured": bool(configured), "registration_enabled": os.environ.get("MAVERICK_GOOGLE_ALLOW_REGISTRATION", "1") == "1",
            "services": [{"id": key, "label": value["label"]} for key, value in google.SERVICES.items()]}


def _same_origin(environ):
    from core.api.app_frame_launch import request_platform_origin
    from core.apps.errors import AppHostingError
    try:
        expected = request_platform_origin(environ)
    except AppHostingError:
        raise google.AccountError("origin_not_allowed", status=403) from None
    # Authentication/account linking is reserved for the top-level shell.
    if environ.get("maverick.app_frame_proxy") or environ.get("HTTP_ORIGIN") != expected:
        raise google.AccountError("origin_not_allowed", status=403)


def _app_inventory(state, context):
    from core.api.app_registry import enabled_app_items, resolve_app_surface
    items = []
    for item in enabled_app_items(state, workspace_id=context.workspace_id, user=context.user, start_path=state.repository_root):
        _, _, parsed = resolve_app_surface(state, workspace_id=context.workspace_id, app_id=item["app_id"], start_path=state.repository_root)
        declaration = parsed.contract.permissions.external_accounts.get("google")
        capabilities = declaration.capabilities if declaration else []
        if capabilities:
            items.append({"app_id": item["app_id"], "name": item["name"], "services": capabilities})
    return items


def _publish_account_change(state, context):
    from core.api.app_event_publication import declared_data_event_resources, publish_declared_app_events
    from core.api.app_registry import resolve_app_surface
    if not getattr(state, "app_event_bus", None):
        return
    for item in _app_inventory(state, context):
        _, _, parsed = resolve_app_surface(state, workspace_id=context.workspace_id, app_id=item["app_id"], start_path=state.repository_root)
        resources = declared_data_event_resources(parsed.contract.capabilities.data_events)
        publish_declared_app_events(state.app_event_bus, {"app_events": [{"resource": resource} for resource in resources]},
            workspace_id=context.workspace_id, app_id=item["app_id"], declared_resources=resources)


def handle_connected_accounts_api(state, environ, start_response):
    path = environ.get("PATH_INFO", "")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if not (path.startswith("/api/auth/google/") or path.startswith("/api/connected-accounts")):
        return None
    secure = _request_is_https(environ)
    if path == "/api/auth/google/status" and method == "GET":
        return json_response(start_response, provider_status(state))
    context = resolve_request_session(state, environ)
    try:
        if path == google.CALLBACK_PATH and method == "GET":
            clear = [_flow_cookie("", secure=secure, clear=True)]
            params = query_params(environ)
            browser = request_cookies(environ).get(FLOW_COOKIE, "")
            if params.get("error"):
                if not browser or not state.account_store.consume_flow(digest(params.get("state", "")), digest(browser), datetime.now(UTC)):
                    raise google.AccountError("google_flow_invalid")
                return _redirect(start_response, "/?google_error=google_consent_cancelled", clear)
            if not browser or not params.get("code") or not params.get("state"):
                raise google.AccountError("google_flow_invalid")
            user, _, mode, selection = complete_flow(state, raw_state=params["state"], browser=browser,
                                                      code=params["code"], context=context)
            if selection is None:
                return _redirect(start_response, "/?google_error=google_workspace_pending", clear)
            if mode == "login":
                expires_at = session_expiry()
                session = state.identity_store.save_auth_session(build_auth_session(
                    session_id=str(uuid4()), user_id=user.user_id, expires_at=expires_at))
                clear.append(session_cookie_header(session.session_id, expires_at=expires_at, secure=secure))
                context = SimpleNamespace(user=user, workspace_id=selection.workspace_id)
            _publish_account_change(state, context)
            return _redirect(start_response, "/?google_connected=1", clear)
        if path == "/api/auth/google/start" and method == "POST":
            _same_origin(environ)
            configured = urlsplit(google.redirect_uri())
            if environ.get("HTTP_ORIGIN") != f"{configured.scheme}://{configured.netloc}":
                raise google.AccountError("origin_not_allowed", status=403)
            body = read_json_body(environ)
            result, browser = start_flow(state, mode=body.get("mode", "login"), services=body.get("services", []), context=context)
            return json_response(start_response, result, headers=[_flow_cookie(browser, secure=secure)])
        if not path.startswith("/api/connected-accounts"):
            return json_response(start_response, {"error": "not_found"}, status="404 Not Found")
        if context is None:
            raise google.AccountError("authentication_required", status=401)
        if environ.get("maverick.app_frame_proxy"):
            raise google.AccountError("origin_not_allowed", status=403)
        if method != "GET":
            _same_origin(environ)
        if path == "/api/connected-accounts" and method == "GET":
            selection = state.account_store.get_selection(context.user.user_id, context.workspace_id)
            return json_response(start_response, {"items": [public_account(account) for account in state.account_store.list_accounts(context.user.user_id)],
                "selection": {"account_id": selection.account_id, "disabled_apps": selection.disabled_apps} if selection else None,
                "apps": _app_inventory(state, context), "google": provider_status(state)})
        if path == "/api/connected-accounts/select" and method == "POST":
            body = read_json_body(environ)
            select_account(state, user_id=context.user.user_id, workspace_id=context.workspace_id, account_id=str(body.get("account_id") or ""))
            _publish_account_change(state, context)
            return json_response(start_response, {"status": "selected"})
        if path == "/api/connected-accounts/app-access" and method == "POST":
            body = read_json_body(environ)
            app_id = str(body.get("app_id") or "")
            if not isinstance(body.get("enabled"), bool) or app_id not in {item["app_id"] for item in _app_inventory(state, context)}:
                raise google.AccountError("invalid_app_access")
            selection = state.account_store.get_selection(context.user.user_id, context.workspace_id)
            if not selection:
                raise google.AccountError("account_not_selected")
            disabled = set(selection.disabled_apps)
            disabled.discard(app_id) if body["enabled"] else disabled.add(app_id)
            state.account_store.save_selection(replace(selection, disabled_apps=sorted(disabled)))
            _publish_account_change(state, context)
            return json_response(start_response, {"status": "updated"})
        if path.startswith("/api/connected-accounts/") and method == "DELETE":
            account_id = path.removeprefix("/api/connected-accounts/")
            result = disconnect_account(state, user_id=context.user.user_id, account_id=account_id)
            _publish_account_change(state, context)
            return json_response(start_response, result)
        return json_response(start_response, {"error": "not_found"}, status="404 Not Found")
    except (google.AccountError, UserNotFoundError) as error:
        code = error.code if isinstance(error, google.AccountError) else "google_user_unavailable"
        if path == google.CALLBACK_PATH:
            return _redirect(start_response, "/?google_error=" + code, [_flow_cookie("", secure=secure, clear=True)])
        return json_response(start_response, {"error": code}, status=status_line(getattr(error, "status", 400)))
