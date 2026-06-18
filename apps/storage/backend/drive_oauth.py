"""Google Drive OAuth flow helpers for Storage."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from drive_connection_store import (
    append_audit,
    get_connection,
    list_connections,
    now_timestamp,
    public_connection,
    read_state,
    remove_connection,
    replace_connection,
)
from errors import StorageValidationError


GOOGLE_DRIVE_PROVIDER = "google_drive"
GOOGLE_DRIVE_CLIENT_ID_SECRET = "google-drive-oauth-client-id"
GOOGLE_DRIVE_CLIENT_SECRET_SECRET = "google-drive-oauth-client-secret"
GOOGLE_DRIVE_REFRESH_TOKEN_SECRET = "google-drive-refresh-token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_PROFILE_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
DEFAULT_REDIRECT_PATH = "/apps/storage/oauth/callback"
LEGACY_ROOT_SHELL_REDIRECT_PATH = "/app/storage/oauth/callback"
OAUTH_STATE_TTL_SECONDS = 900

ACCESS_MODE_SCOPES = {
    "full_read": ["https://www.googleapis.com/auth/drive.readonly", "openid", "email"],
    "full_rw": ["https://www.googleapis.com/auth/drive", "openid", "email"],
    "picker_limited": ["https://www.googleapis.com/auth/drive.file", "openid", "email"],
}

HttpTransport = Callable[[str, str, dict[str, Any]], tuple[int, dict[str, Any] | bytes]]


def provider_status(
    app_secrets: object | None = None,
    connections: list[dict[str, Any]] | None = None,
    *,
    secrets_requested: bool = True,
) -> dict[str, Any]:
    secrets_map = _secret_map(app_secrets)
    missing = [
        name
        for name in [GOOGLE_DRIVE_CLIENT_ID_SECRET, GOOGLE_DRIVE_CLIENT_SECRET_SECRET]
        if not str(secrets_map.get(name) or "").strip()
    ]
    public_missing = missing if secrets_requested else []
    connected = any(
        item.get("provider") == GOOGLE_DRIVE_PROVIDER and item.get("status") == "connected"
        for item in connections or []
    )
    if connected:
        provider_state = "connected"
    elif secrets_requested and missing:
        provider_state = "needs_secret_grant"
    else:
        provider_state = "ready_for_oauth"
    secret_status = (
        "missing"
        if secrets_requested and missing
        else ("available" if secrets_requested else "not_requested")
    )
    return {
        "provider": GOOGLE_DRIVE_PROVIDER,
        "providers": [
            {
                "provider": GOOGLE_DRIVE_PROVIDER,
                "connected": connected,
                "configured": not missing if secrets_requested else connected,
                "status": provider_state,
                "secret_status": secret_status,
            }
        ],
        "required_secrets": [GOOGLE_DRIVE_CLIENT_ID_SECRET, GOOGLE_DRIVE_CLIENT_SECRET_SECRET],
        "missing_secrets": public_missing,
        "secret_status": secret_status,
        "callback_path": DEFAULT_REDIRECT_PATH,
        "access_modes": sorted(ACCESS_MODE_SCOPES),
        "default_access_mode": "full_rw",
    }


def list_drive_connections(data_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    connections = list_connections(data_root)
    return {
        "connections": connections,
        **provider_status(
            payload.get("_app_secrets"),
            connections,
            secrets_requested=_oauth_client_secrets_requested(payload.get("_app_secret_request")),
        ),
    }


def start_oauth(data_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    provider = _provider(payload.get("provider"))
    access_mode = _access_mode(payload.get("access_mode") or payload.get("mode") or "full_rw")
    secrets_map = _secret_map(payload.get("_app_secrets"))
    client_id = str(secrets_map.get(GOOGLE_DRIVE_CLIENT_ID_SECRET) or "").strip()
    client_secret = str(secrets_map.get(GOOGLE_DRIVE_CLIENT_SECRET_SECRET) or "").strip()
    if not client_id or not client_secret:
        append_audit(
            data_root,
            "drive.oauth.start_missing_secret",
            "drive_connection",
            provider,
            {"provider": provider, "access_mode": access_mode},
        )
        return {
            "flow": "start_oauth",
            "provider": provider,
            "access_mode": access_mode,
            "status": "not_configured",
            "detail": "Grant google-drive-oauth-client-id and google-drive-oauth-client-secret through Vault/Core Secrets before starting Drive OAuth.",
            **provider_status(secrets_map, list_connections(data_root)),
        }
    issued_at = datetime.now(tz=UTC)
    expires_at = issued_at + timedelta(seconds=OAUTH_STATE_TTL_SECONDS)
    state = f"drive_oauth_{secrets.token_urlsafe(32)}"
    connection_id = f"drive_conn_{secrets.token_hex(8)}"
    redirect_uri = _allowed_redirect_uri(payload.get("redirect_uri") or DEFAULT_REDIRECT_PATH)
    connection = {
        "id": connection_id,
        "provider": provider,
        "status": "pending",
        "access_mode": access_mode,
        "scopes": ACCESS_MODE_SCOPES[access_mode],
        "created_at": issued_at.isoformat(),
        "updated_at": issued_at.isoformat(),
        "external_refs": {
            "oauth_state_hash": _state_hash(state),
            "oauth_state_expires_at": expires_at.isoformat(),
            "oauth_redirect_uri": redirect_uri,
        },
    }
    replace_connection(data_root, connection)
    append_audit(
        data_root,
        "drive.oauth.start",
        "drive_connection",
        connection_id,
        {"provider": provider, "access_mode": access_mode, "redirect_path": urlparse(redirect_uri).path or redirect_uri},
    )
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(ACCESS_MODE_SCOPES[access_mode]),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
    )
    return {
        "flow": "start_oauth",
        "provider": provider,
        "access_mode": access_mode,
        "status": "authorization_required",
        "authorization_url": f"{GOOGLE_AUTH_URL}?{query}",
        "state": state,
        "expires_in_seconds": OAUTH_STATE_TTL_SECONDS,
        "scopes": ACCESS_MODE_SCOPES[access_mode],
        "callback_path": DEFAULT_REDIRECT_PATH,
        "connection": public_connection(connection),
    }


def complete_oauth(
    data_root: Path,
    payload: dict[str, Any],
    *,
    allow_platform_secret_writes: bool = False,
    transport: HttpTransport | None = None,
) -> dict[str, Any]:
    _provider(payload.get("provider"))
    state_value = _required_string(payload.get("state"), "state", operation="drive_connections.complete_oauth")
    code = _required_string(payload.get("code"), "code", operation="drive_connections.complete_oauth")
    state_record = _pending_connection_for_state(data_root, state_value)
    secrets_map = _secret_map(payload.get("_app_secrets"))
    client_id = str(secrets_map.get(GOOGLE_DRIVE_CLIENT_ID_SECRET) or "").strip()
    client_secret = str(secrets_map.get(GOOGLE_DRIVE_CLIENT_SECRET_SECRET) or "").strip()
    if not client_id or not client_secret:
        append_audit(
            data_root,
            "drive.oauth.complete_missing_secret",
            "drive_connection",
            state_record["id"],
            {"provider": GOOGLE_DRIVE_PROVIDER, "access_mode": state_record["access_mode"]},
        )
        return {
            "flow": "complete_oauth",
            "provider": GOOGLE_DRIVE_PROVIDER,
            "access_mode": state_record["access_mode"],
            "status": "needs_secret_grant",
            "detail": "OAuth callback was validated, but token exchange requires Google Drive OAuth client secret delivery through Core Secrets.",
        }
    if not allow_platform_secret_writes:
        raise StorageValidationError(
            "Complete Google Drive OAuth through the mounted Storage backend callback so Core Secrets can persist the refresh token.",
            operation="drive_connections.complete_oauth",
        )
    redirect_uri = _completion_redirect_uri(payload, state_record)
    http = transport or default_transport
    token_payload = _exchange_code(http, code=code, client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)
    access_mode = _access_mode(state_record.get("access_mode"))
    scopes = _token_scopes(token_payload)
    _validate_drive_scope(access_mode, scopes)
    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    if not refresh_token:
        raise StorageValidationError(
            "Google did not return a refresh token; restart OAuth consent for offline Drive access.",
            operation="drive_connections.complete_oauth",
        )
    profile = _fetch_profile(http, token_payload.get("access_token"))
    account_email = str(profile.get("email") or "").strip()
    if not account_email:
        raise StorageValidationError(
            "Google profile did not include an account email.",
            operation="drive_connections.complete_oauth",
        )
    duplicate = _connected_account_duplicate(
        data_root,
        state_record=state_record,
        profile=profile,
        account_email=account_email,
    )
    target_connection = duplicate or state_record
    target_connection_id = str(target_connection.get("id") or state_record["id"])
    workspace_id = str(payload.get("_workspace_id") or "default").strip() or "default"
    secret_ref = _scoped_secret_ref(workspace_id=workspace_id, connection_id=target_connection_id)
    grant_id = _scoped_grant_id(workspace_id=workspace_id, connection_id=target_connection_id)
    now = now_timestamp()
    external_refs = {}
    if duplicate is not None and isinstance(target_connection.get("external_refs"), dict):
        external_refs = dict(target_connection.get("external_refs") or {})
    external_refs.update(_connected_external_refs(profile))
    connection = {
        **target_connection,
        "id": target_connection_id,
        "account_email": account_email,
        "display_name": str(profile.get("name") or account_email).strip(),
        "status": "connected",
        "access_mode": access_mode,
        "scopes": scopes,
        "updated_at": now,
        "connected_at": now,
        "credential": {
            "secret_ref": secret_ref,
            "grant_id": grant_id,
            "status": "active",
            "oauth_metadata": _oauth_metadata(token_payload),
        },
        "external_refs": external_refs,
    }
    replace_connection(data_root, connection)
    if duplicate is not None and state_record["id"] != connection["id"]:
        remove_connection(data_root, state_record["id"])
    append_audit(
        data_root,
        "drive.oauth.reconnect" if duplicate is not None else "drive.oauth.complete",
        "drive_connection",
        connection["id"],
        {
            "provider": GOOGLE_DRIVE_PROVIDER,
            "access_mode": access_mode,
            "account_email": account_email,
            **(
                {
                    "pending_connection_id": state_record["id"],
                    "reused_connection_id": connection["id"],
                }
                if duplicate is not None
                else {}
            ),
        },
    )
    return {
        "flow": "complete_oauth",
        "provider": GOOGLE_DRIVE_PROVIDER,
        "access_mode": access_mode,
        "status": "connected",
        "reconnected": duplicate is not None,
        "connection_id": connection["id"],
        "connection": public_connection(connection),
        "credential": {
            "secret_ref": secret_ref,
            "grant_id": grant_id,
            "status": "active",
            "resource_type": "drive_connection",
            "resource_id": connection["id"],
        },
        "platform_secret_writes": [
            {
                "logical_name": GOOGLE_DRIVE_REFRESH_TOKEN_SECRET,
                "resource_type": "drive_connection",
                "resource_id": connection["id"],
                "raw_value": refresh_token,
            }
        ],
    }


def disconnect_connection(data_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    connection_id = _required_string(
        payload.get("connection_id") or payload.get("id"),
        "connection_id",
        operation="drive_connections.disconnect",
    )
    try:
        connection = get_connection(data_root, connection_id)
    except ValueError as error:
        raise StorageValidationError(str(error), operation="drive_connections.disconnect") from error
    previous_status = str(connection.get("status") or "")
    now = now_timestamp()
    disconnected = {
        **connection,
        "status": "disconnected",
        "updated_at": now,
        "disconnected_at": now,
        "credential": {
            **dict(connection.get("credential") or {}),
            "status": "disconnected",
        },
    }
    replace_connection(data_root, disconnected)
    append_audit(
        data_root,
        "drive.connections.disconnect",
        "drive_connection",
        connection_id,
        {
            "provider": GOOGLE_DRIVE_PROVIDER,
            "previous_status": previous_status,
            "new_status": "disconnected",
            "core_secret_revocation": "not_supported_by_storage_backend",
        },
    )
    return {
        "status": "disconnected",
        "connection_id": connection_id,
        "previous_status": previous_status,
        "connection": public_connection(disconnected),
        "core_secret_revocation": {
            "status": "not_supported_by_storage_backend",
            "detail": "Storage records the local disconnect and disables connection metadata; Core Secrets revocation must be performed through Vault/Core Secrets administration surfaces.",
        },
    }


def default_transport(method: str, url: str, request: dict[str, Any]) -> tuple[int, dict[str, Any] | bytes]:
    headers = {str(key): str(value) for key, value in dict(request.get("headers") or {}).items()}
    data = request.get("data")
    encoded_data: bytes | None = None
    if isinstance(data, dict):
        encoded_data = urlencode(data).encode("utf-8")
    elif isinstance(data, bytes):
        encoded_data = data
    elif isinstance(data, str):
        encoded_data = data.encode("utf-8")
    try:
        with urlopen(Request(url, data=encoded_data, headers=headers, method=method.upper()), timeout=20) as response:
            if request.get("response_type") == "bytes":
                max_bytes = int(request.get("max_bytes") or 0)
                payload = response.read(max_bytes + 1 if max_bytes > 0 else -1)
                return int(response.status), payload
            payload = json.loads(response.read().decode("utf-8") or "{}")
            return int(response.status), payload if isinstance(payload, dict) else {}
    except HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        return int(error.code), payload if isinstance(payload, dict) else {}
    except URLError as error:
        raise StorageValidationError(
            "Google OAuth is currently unavailable.",
            operation="drive_connections.complete_oauth",
        ) from error


def _exchange_code(http: HttpTransport, *, code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict[str, Any]:
    status, payload = http(
        "POST",
        GOOGLE_TOKEN_URL,
        {
            "headers": {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            "data": {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        },
    )
    if status >= 400:
        error_code = str(payload.get("error") or "oauth_exchange_failed") if isinstance(payload, dict) else "oauth_exchange_failed"
        raise StorageValidationError(
            f"Google Drive OAuth token exchange failed: {error_code}.",
            operation="drive_connections.complete_oauth",
        )
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise StorageValidationError(
            "Google Drive OAuth token exchange did not return an access token.",
            operation="drive_connections.complete_oauth",
        )
    return payload


def _fetch_profile(http: HttpTransport, access_token: Any) -> dict[str, Any]:
    token = str(access_token or "").strip()
    if not token:
        return {}
    status, payload = http("GET", GOOGLE_PROFILE_URL, {"headers": {"Authorization": f"Bearer {token}"}})
    if status >= 400 or not isinstance(payload, dict):
        return {}
    return payload


def _pending_connection_for_state(data_root: Path, state_value: str) -> dict[str, Any]:
    state_hash = _state_hash(state_value)
    current_time = datetime.now(tz=UTC)
    expired_match = False
    for connection in read_state(data_root).get("connections", []):
        if connection.get("status") != "pending":
            continue
        external_refs = connection.get("external_refs") if isinstance(connection.get("external_refs"), dict) else {}
        if external_refs.get("oauth_state_hash") != state_hash:
            continue
        expires_at = _datetime_value(external_refs.get("oauth_state_expires_at"))
        if expires_at is not None and expires_at <= current_time:
            expired_match = True
            continue
        return connection
    if expired_match:
        raise StorageValidationError("OAuth state has expired; start a new Drive connection flow.", operation="drive_connections.complete_oauth")
    raise StorageValidationError("OAuth state was not found or is no longer pending.", operation="drive_connections.complete_oauth")


def _completion_redirect_uri(payload: dict[str, Any], state_record: dict[str, Any]) -> str:
    external_refs = state_record.get("external_refs") if isinstance(state_record.get("external_refs"), dict) else {}
    stored = str(external_refs.get("oauth_redirect_uri") or "").strip()
    supplied = str(payload.get("redirect_uri") or "").strip()
    if stored and supplied and supplied != stored:
        raise StorageValidationError("OAuth callback redirect_uri does not match the started flow.", operation="drive_connections.complete_oauth")
    return _allowed_redirect_uri(supplied or stored or DEFAULT_REDIRECT_PATH)


def _allowed_redirect_uri(value: object) -> str:
    uri = str(value or "").strip()
    if not uri:
        raise StorageValidationError("redirect_uri is required for Drive OAuth", operation="drive_connections.start_oauth")
    parsed = urlparse(uri)
    allowed = {DEFAULT_REDIRECT_PATH, LEGACY_ROOT_SHELL_REDIRECT_PATH}
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise StorageValidationError("redirect_uri must be an http(s) URL", operation="drive_connections.start_oauth")
        if parsed.path not in allowed or parsed.params or parsed.query or parsed.fragment:
            raise StorageValidationError(
                f"redirect_uri must target one of: {', '.join(sorted(allowed))}",
                operation="drive_connections.start_oauth",
            )
        return uri
    if uri not in allowed:
        raise StorageValidationError(
            f"redirect_uri must target one of: {', '.join(sorted(allowed))}",
            operation="drive_connections.start_oauth",
        )
    return uri


def _provider(value: object) -> str:
    provider = str(value or GOOGLE_DRIVE_PROVIDER).strip().lower()
    if provider != GOOGLE_DRIVE_PROVIDER:
        raise StorageValidationError(
            "Drive OAuth supports provider `google_drive` only.",
            operation="drive_connections.start_oauth",
            allowed_values={"provider": [GOOGLE_DRIVE_PROVIDER]},
        )
    return provider


def _access_mode(value: object) -> str:
    mode = str(value or "full_rw").strip().lower()
    if mode not in ACCESS_MODE_SCOPES:
        raise StorageValidationError(
            "Unsupported Google Drive OAuth access mode.",
            operation="drive_connections.start_oauth",
            allowed_values={"access_mode": sorted(ACCESS_MODE_SCOPES)},
            example={"action": "drive_connections.start_oauth", "provider": "google_drive", "access_mode": "full_rw"},
        )
    return mode


def _required_string(value: object, field: str, *, operation: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise StorageValidationError(f"{field} is required.", operation=operation)
    return text


def _token_scopes(payload: dict[str, Any]) -> list[str]:
    return _dedupe(str(payload.get("scope") or "").split())


def _validate_drive_scope(access_mode: str, scopes: list[str]) -> None:
    required = ACCESS_MODE_SCOPES[access_mode][0]
    if required not in scopes:
        raise StorageValidationError(
            f"Google OAuth did not grant required Drive scope for {access_mode}.",
            operation="drive_connections.complete_oauth",
            allowed_values={"required_scope": [required]},
        )


def _oauth_metadata(token_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "expires_in": token_payload.get("expires_in"),
        "scope": token_payload.get("scope"),
        "received_at": now_timestamp(),
    }


def _connected_external_refs(profile: dict[str, Any]) -> dict[str, Any]:
    subject = str(profile.get("id") or profile.get("sub") or "").strip()
    return {"google_subject": subject} if subject else {}


def _connected_account_duplicate(
    data_root: Path,
    *,
    state_record: dict[str, Any],
    profile: dict[str, Any],
    account_email: str,
) -> dict[str, Any] | None:
    subject = str(profile.get("id") or profile.get("sub") or "").strip()
    email_key = account_email.casefold()
    for connection in read_state(data_root).get("connections", []):
        if str(connection.get("id") or "") == str(state_record.get("id") or ""):
            continue
        if connection.get("status") != "connected":
            continue
        external_refs = connection.get("external_refs") if isinstance(connection.get("external_refs"), dict) else {}
        existing_subject = str(external_refs.get("google_subject") or "").strip()
        existing_email = str(connection.get("account_email") or "").strip().casefold()
        if subject and existing_subject == subject:
            return connection
        if email_key and existing_email == email_key:
            return connection
    return None


def _secret_map(app_secrets: object | None) -> dict[str, object]:
    return app_secrets if isinstance(app_secrets, dict) else {}


def _oauth_client_secrets_requested(secret_request: object) -> bool:
    if not isinstance(secret_request, dict):
        return False
    names = set(_logical_names(secret_request.get("logical_names")))
    for selector in secret_request.get("selectors") or []:
        if isinstance(selector, dict):
            names.update(_logical_names(selector.get("logical_names")))
    return bool({GOOGLE_DRIVE_CLIENT_ID_SECRET, GOOGLE_DRIVE_CLIENT_SECRET_SECRET} & names)


def _logical_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _scoped_secret_ref(*, workspace_id: str, connection_id: str) -> str:
    alias = "-".join(
        _secret_segment(item)
        for item in [workspace_id, "storage", GOOGLE_DRIVE_REFRESH_TOKEN_SECRET, "drive_connection", connection_id]
    )
    return f"platform:secret-alias/{alias}"


def _scoped_grant_id(*, workspace_id: str, connection_id: str) -> str:
    return ":".join(
        _secret_segment(item)
        for item in ["grant", workspace_id, "storage", GOOGLE_DRIVE_REFRESH_TOKEN_SECRET, "drive_connection", connection_id]
    )


def _secret_segment(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-") or "item"


def _state_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _datetime_value(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
