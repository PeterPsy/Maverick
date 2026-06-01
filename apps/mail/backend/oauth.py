"""OAuth flow helpers for Mail providers."""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from datetime import UTC, datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from database import connect, ensure_schema, now_timestamp, oauth_flow_expiry
from providers.gmail import GMAIL_SCOPES, GmailProvider
from store import audit

GMAIL_CLIENT_ID_SECRET = "gmail-oauth-client-id"
GMAIL_CLIENT_SECRET_SECRET = "gmail-oauth-client-secret"
GMAIL_REFRESH_TOKEN_SECRET = "gmail-refresh-token"
DEFAULT_REDIRECT_PATH = "/apps/mail/oauth/callback"
LEGACY_ROOT_SHELL_REDIRECT_PATH = "/app/mail/oauth/callback"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def provider_status(app_secrets: object | None = None, connections: list[dict[str, object]] | None = None) -> dict[str, object]:
    secrets_map = _secret_map(app_secrets)
    connection_items = connections or []
    has_gmail = any(item.get("provider") == "gmail" and item.get("status") == "connected" for item in connection_items)
    imap_connections = [item for item in connection_items if item.get("provider") == "imap_smtp" and item.get("status") != "disconnected"]
    imap_connected = any(item.get("status") == "connected" for item in imap_connections)
    return {
        "providers": [
            _provider_payload(
                "gmail",
                connected=has_gmail,
                configured=bool(secrets_map.get(GMAIL_CLIENT_ID_SECRET)),
                status="connected" if has_gmail else ("needs_secret_grant" if not secrets_map.get(GMAIL_CLIENT_ID_SECRET) else "ready_for_oauth"),
            ),
            _provider_payload(
                "imap_smtp",
                connected=imap_connected,
                configured=bool(imap_connections),
                status=("connected" if imap_connected else (str(imap_connections[0].get("status")) if imap_connections else "not_configured")),
            ),
        ],
        "required_secrets": [GMAIL_CLIENT_ID_SECRET, GMAIL_CLIENT_SECRET_SECRET, "mailbox-password"],
        "callback_path": DEFAULT_REDIRECT_PATH,
    }


def start_oauth(data_root: Path, payload: dict[str, object]) -> dict[str, object]:
    ensure_schema(data_root)
    provider = str(payload.get("provider") or "gmail").strip().lower()
    if provider != "gmail":
        raise ValueError(f"Unsupported OAuth provider `{provider}`")
    secrets_map = _secret_map(payload.get("_app_secrets"))
    client_id = str(secrets_map.get(GMAIL_CLIENT_ID_SECRET) or "").strip()
    redirect_uri = _allowed_redirect_uri(payload.get("redirect_uri") or DEFAULT_REDIRECT_PATH)
    if not client_id:
        audit(data_root, "oauth.start_missing_secret", "mail_connection", provider, {"provider": provider})
        return {
            "flow": "start_oauth",
            "provider": provider,
            "status": "not_configured",
            "detail": "Grant gmail-oauth-client-id and gmail-oauth-client-secret through Vault/Core Secrets before starting Gmail OAuth.",
            **provider_status(secrets_map),
        }
    state = f"mail_oauth_{secrets.token_urlsafe(24)}"
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO oauth_flows(state, provider, status, scopes_json, redirect_uri, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (state, provider, "pending", json.dumps(GMAIL_SCOPES, ensure_ascii=True), redirect_uri, now, oauth_flow_expiry()),
        )
    audit(data_root, "oauth.start", "mail_connection", provider, {"provider": provider, "redirect_path": DEFAULT_REDIRECT_PATH})
    return {
        "flow": "start_oauth",
        "provider": provider,
        "status": "authorization_required",
        "authorization_url": GmailProvider().authorization_url(client_id=client_id, redirect_uri=redirect_uri, state=state),
        "state": state,
        "expires_in_seconds": 900,
        "scopes": GMAIL_SCOPES,
        "callback_path": DEFAULT_REDIRECT_PATH,
    }


def complete_oauth(data_root: Path, payload: dict[str, object]) -> dict[str, object]:
    ensure_schema(data_root)
    state = str(payload.get("state") or "").strip()
    code = str(payload.get("code") or "").strip()
    if not state or not code:
        raise ValueError("state and code are required")
    secrets_map = _secret_map(payload.get("_app_secrets"))
    with connect(data_root) as db:
        flow = db.execute("SELECT * FROM oauth_flows WHERE state = ? AND status = 'pending'", (state,)).fetchone()
        if flow is None:
            raise ValueError("OAuth state was not found or is no longer pending")
        if _is_expired(str(flow["expires_at"])):
            db.execute("UPDATE oauth_flows SET status = 'expired' WHERE state = ?", (state,))
            raise ValueError("OAuth state has expired; start a new Gmail connection flow")
    audit(data_root, "oauth.complete_pending_exchange", "mail_connection", "gmail", {"state": state})
    client_id = str(secrets_map.get(GMAIL_CLIENT_ID_SECRET) or "").strip()
    client_secret = str(secrets_map.get(GMAIL_CLIENT_SECRET_SECRET) or "").strip()
    if not client_id or not client_secret:
        return {
            "flow": "complete_oauth",
            "provider": "gmail",
            "status": "needs_secret_grant",
            "detail": "OAuth callback was validated, but token exchange requires Gmail OAuth client secret delivery through Core Secrets.",
        }
    token_payload = _exchange_code(
        code=code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=str(flow["redirect_uri"]),
    )
    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    access_token = str(token_payload.get("access_token") or "").strip()
    if not refresh_token:
        raise ValueError("Google did not return a refresh token; restart OAuth consent for offline access.")
    _validate_granted_scopes(token_payload.get("scope"))
    profile = GmailProvider().fetch_profile(access_token=access_token)
    email_address = str(profile.get("emailAddress") or "").strip()
    if not email_address:
        raise ValueError("Gmail profile did not include an email address")
    workspace_id = str(payload.get("_workspace_id") or "default").strip() or "default"
    connection_id = f"mail_connection_gmail_{_secret_segment(email_address)}"
    secret_ref = _scoped_secret_ref(workspace_id=workspace_id, connection_id=connection_id)
    grant_id = _scoped_grant_id(workspace_id=workspace_id, connection_id=connection_id)
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO connections(id, provider, email_address, display_name, status, scopes_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              email_address = excluded.email_address,
              display_name = excluded.display_name,
              status = excluded.status,
              scopes_json = excluded.scopes_json,
              updated_at = excluded.updated_at
            """,
            (
                connection_id,
                "gmail",
                email_address,
                email_address,
                "connected",
                json.dumps(sorted(_granted_scopes(token_payload.get("scope"))), ensure_ascii=True),
                now,
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO oauth_credentials(id, connection_id, provider, secret_ref, grant_id, encrypted_token_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              secret_ref = excluded.secret_ref,
              grant_id = excluded.grant_id,
              encrypted_token_json = excluded.encrypted_token_json,
              status = excluded.status,
              updated_at = excluded.updated_at
            """,
            (
                f"oauth_credential_{connection_id}",
                connection_id,
                "gmail",
                secret_ref,
                grant_id,
                json.dumps(_token_metadata(token_payload), ensure_ascii=True, sort_keys=True),
                "active",
                now,
                now,
            ),
        )
        db.execute("UPDATE oauth_flows SET status = 'completed' WHERE state = ?", (state,))
    audit(data_root, "oauth.complete", "mail_connection", connection_id, {"provider": "gmail", "email_address": email_address})
    return {
        "flow": "complete_oauth",
        "provider": "gmail",
        "status": "connected",
        "connection_id": connection_id,
        "connection": {
            "id": connection_id,
            "provider": "gmail",
            "email_address": email_address,
            "display_name": email_address,
            "status": "connected",
            "scopes": sorted(_granted_scopes(token_payload.get("scope"))),
        },
        "credential": {
            "secret_ref": secret_ref,
            "grant_id": grant_id,
            "status": "active",
        },
        "platform_secret_writes": [
            {
                "logical_name": GMAIL_REFRESH_TOKEN_SECRET,
                "resource_type": "mail_connection",
                "resource_id": connection_id,
                "raw_value": refresh_token,
            }
        ],
    }


def _provider_payload(provider: str, *, connected: bool, configured: bool, status: str) -> dict[str, object]:
    return {"provider": provider, "connected": connected, "configured": configured, "status": status}


def _secret_map(app_secrets: object | None) -> dict[str, object]:
    return app_secrets if isinstance(app_secrets, dict) else {}


def _exchange_code(*, code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict[str, object]:
    body = urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = Request(
        GOOGLE_TOKEN_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _granted_scopes(raw_scope: object) -> set[str]:
    return {scope.strip() for scope in str(raw_scope or "").split() if scope.strip()}


def _validate_granted_scopes(raw_scope: object) -> None:
    granted = _granted_scopes(raw_scope)
    missing = [scope for scope in GMAIL_SCOPES if scope not in granted]
    if missing:
        raise ValueError(f"Google OAuth did not grant required Gmail scopes: {', '.join(missing)}")


def _token_metadata(token_payload: dict[str, object]) -> dict[str, object]:
    return {
        "token_type": token_payload.get("token_type"),
        "expires_in": token_payload.get("expires_in"),
        "scope": token_payload.get("scope"),
        "received_at": now_timestamp(),
    }


def _secret_segment(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-") or "item"


def _scoped_secret_ref(*, workspace_id: str, connection_id: str) -> str:
    alias = "-".join(
        _secret_segment(item)
        for item in [workspace_id, "mail", GMAIL_REFRESH_TOKEN_SECRET, "mail_connection", connection_id]
    )
    return f"platform:secret-alias/{alias}"


def _scoped_grant_id(*, workspace_id: str, connection_id: str) -> str:
    return ":".join(
        _secret_segment(item)
        for item in ["grant", workspace_id, "mail", GMAIL_REFRESH_TOKEN_SECRET, "mail_connection", connection_id]
    )


def _allowed_redirect_uri(value: object) -> str:
    uri = str(value or "").strip()
    if not uri:
        raise ValueError("redirect_uri is required for Gmail OAuth")
    parsed = urlparse(uri)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("redirect_uri must be an http(s) URL")
        if parsed.path not in _allowed_redirect_paths() or parsed.params or parsed.query or parsed.fragment:
            raise ValueError(f"redirect_uri must target one of: {', '.join(sorted(_allowed_redirect_paths()))}")
        return uri
    if uri not in _allowed_redirect_paths():
        raise ValueError(f"redirect_uri must target one of: {', '.join(sorted(_allowed_redirect_paths()))}")
    return uri


def _allowed_redirect_paths() -> set[str]:
    return {DEFAULT_REDIRECT_PATH, LEGACY_ROOT_SHELL_REDIRECT_PATH}


def _is_expired(value: str) -> bool:
    try:
        expires_at = datetime.fromisoformat(value)
    except ValueError:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(tz=UTC)
