"""Google Calendar OAuth flow helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import secrets
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from constants import GOOGLE_PROVIDER, GOOGLE_REFRESH_TOKEN_LOGICAL_NAME, MAX_PROVIDER_ID_LENGTH
from connection_records import normalize_connection
from scalars import clean_string
from store import read_state, update_state
from time_values import format_time, iso_time


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_PROFILE_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
GOOGLE_CALENDAR_LIST_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
REQUIRED_GOOGLE_CALENDAR_SCOPES = [GOOGLE_CALENDAR_EVENTS_SCOPE, GOOGLE_CALENDAR_LIST_READONLY_SCOPE]
DEFAULT_SCOPES = [*REQUIRED_GOOGLE_CALENDAR_SCOPES, "openid", "email"]
OAUTH_STATE_TTL_SECONDS = 600

HttpTransport = Callable[[str, str, dict[str, Any]], tuple[int, dict[str, Any]]]


class CalendarOAuthError(ValueError):
    """OAuth error with a stable response code and optional structured context."""

    def __init__(self, code: str, detail: str, *, status_code: int = 400, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.extra = extra or {}


def provider_status(
    data_root,
    *,
    app_secrets: dict[str, str] | None = None,
    app_secret_errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return redaction-safe Google Calendar provider setup status."""
    connections = _active_connections(read_state(data_root).get("connections", []))
    secrets_payload = app_secrets or {}
    missing = _missing_secret_names(secrets_payload, ["google-oauth-client-id", "google-oauth-client-secret"])
    errors = _secret_error_names(app_secret_errors)
    configured = not missing and not errors
    return {
        "action": "calendar_connections.provider_status",
        "provider": GOOGLE_PROVIDER,
        "status": "configured" if configured else "missing_grant",
        "configured": configured,
        "missing_secrets": missing,
        "secret_errors": errors,
        "connection_count": len(connections),
        "connected_count": len([item for item in connections if item.get("status") == "connected"]),
    }


def list_connections(data_root) -> dict[str, Any]:
    """List redaction-safe Calendar connection records."""
    state = _prune_expired_pending_connections(data_root)
    connections = [_public_connection(item) for item in state.get("connections", [])]
    return {"action": "calendar_connections.list", "connections": connections}


def start_oauth(
    data_root,
    body: dict[str, Any],
    *,
    app_id: str,
    app_secrets: dict[str, str] | None = None,
    app_secret_errors: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Start Google Calendar OAuth and persist a short-lived pending state."""
    _require_provider(body)
    client_id = _required_app_secret(
        app_secrets,
        app_secret_errors,
        "google-oauth-client-id",
        detail="Google OAuth client id is unavailable through Core Secrets.",
    )
    issued_at = (now or datetime.now(UTC)).astimezone(UTC)
    state = secrets.token_urlsafe(32)
    connection_id = f"cal_conn_{secrets.token_hex(8)}"
    redirect_uri = _redirect_uri(body, app_id=app_id)
    scopes = _requested_scopes(body.get("scope") or body.get("scopes"))
    expires_at = issued_at + timedelta(seconds=OAUTH_STATE_TTL_SECONDS)
    pending_connection = {
        "id": connection_id,
        "provider": GOOGLE_PROVIDER,
        "account_id": "",
        "account_label": "Google Calendar",
        "status": "pending",
        "scopes": scopes,
        "created_at": format_time(issued_at),
        "updated_at": format_time(issued_at),
        "external_refs": {
            "oauth_state_hash": _state_hash(state),
            "oauth_state_expires_at": format_time(expires_at),
            "oauth_redirect_uri": redirect_uri,
        },
    }
    update_state(data_root, lambda current: _replace_connection(current, pending_connection))
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
    )
    return {
        "action": "calendar_connections.start_oauth",
        "provider": GOOGLE_PROVIDER,
        "authorization_url": f"{GOOGLE_AUTH_URL}?{query}",
        "state": state,
        "expires_at": format_time(expires_at),
        "connection": _public_connection(normalize_connection(pending_connection)),
    }


def complete_oauth(
    data_root,
    body: dict[str, Any],
    *,
    app_id: str,
    app_secrets: dict[str, str] | None = None,
    app_secret_errors: list[dict[str, Any]] | None = None,
    allow_platform_secret_writes: bool = False,
    transport: HttpTransport | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Complete Google Calendar OAuth and request Core Secrets token persistence."""
    _require_provider(body)
    code = _required_callback_string(body.get("code"), "code")
    state_value = _required_callback_string(body.get("state"), "state")
    if not allow_platform_secret_writes:
        raise CalendarOAuthError(
            "secret_write_unavailable",
            "Complete Google Calendar OAuth through the backend callback so Core Secrets can persist the refresh token.",
        )
    client_id = _required_app_secret(
        app_secrets,
        app_secret_errors,
        "google-oauth-client-id",
        detail="Google OAuth client id is unavailable through Core Secrets.",
    )
    client_secret = _required_app_secret(
        app_secrets,
        app_secret_errors,
        "google-oauth-client-secret",
        detail="Google OAuth client secret is unavailable through Core Secrets.",
    )
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    state = read_state(data_root)
    state_record = _pending_connection_for_state(state, state_value, now=current_time)
    redirect_uri = _completion_redirect_uri(body, app_id=app_id, state_record=state_record)
    http = transport or default_transport
    token_payload = _exchange_code(
        http,
        code=code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    scopes = _token_scopes(token_payload)
    _validate_calendar_scope(scopes)
    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    if not refresh_token:
        raise CalendarOAuthError(
            "missing_oauth_grant",
            "Google did not return a refresh token. Restart OAuth and approve offline Calendar access.",
        )
    profile = _fetch_profile(http, token_payload.get("access_token"))
    account_id, account_label = _account_identity(body, profile, state_record)
    reconnect_target = _reconnect_target_connection(
        state,
        state_record=state_record,
        profile=profile,
        account_id=account_id,
    )
    base_record = reconnect_target or state_record
    updated_at = format_time(current_time)
    connection = normalize_connection(
        {
            **base_record,
            "provider": GOOGLE_PROVIDER,
            "account_id": account_id,
            "account_label": account_label,
            "status": "connected",
            "scopes": scopes,
            "updated_at": updated_at,
            "external_refs": _connected_external_refs(base_record, profile),
        }
    )
    update_state(
        data_root,
        lambda current: _replace_completed_connection(
            current,
            state_record=state_record,
            connection=connection,
        ),
    )
    result: dict[str, Any] = {
        "action": "calendar_connections.complete_oauth",
        "provider": GOOGLE_PROVIDER,
        "connection": _public_connection(connection),
    }
    result["platform_secret_writes"] = [
        {
            "logical_name": GOOGLE_REFRESH_TOKEN_LOGICAL_NAME,
            "resource_type": "calendar_connection",
            "resource_id": connection["id"],
            "raw_value": refresh_token,
        }
    ]
    return result


def disconnect_connection(
    data_root,
    body: dict[str, Any],
    *,
    app_secrets: dict[str, str] | None = None,
    app_secret_errors: list[dict[str, Any]] | None = None,
    transport: HttpTransport | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Disconnect one Google Calendar connection without exposing its refresh token."""
    _require_provider(body)
    connection_id = clean_string(
        body.get("connection_id") or body.get("connectionId"),
        "connection_id",
        required=True,
        max_length=MAX_PROVIDER_ID_LENGTH,
    )
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    state = read_state(data_root)
    connection = _connection_by_id(state, connection_id)
    if connection["provider"] != GOOGLE_PROVIDER:
        raise CalendarOAuthError("unsupported_provider", "Calendar disconnect currently supports provider `google` only.")
    if connection["status"] == "connected":
        _revoke_refresh_token(app_secrets=app_secrets, app_secret_errors=app_secret_errors, transport=transport)
    disconnected = normalize_connection(
        {
            **connection,
            "status": "disabled",
            "updated_at": format_time(current_time),
            "external_refs": {
                **dict(connection.get("external_refs") or {}),
                "disconnected_at": format_time(current_time),
            },
        }
    )
    update_state(data_root, lambda current: _replace_connection(current, disconnected))
    return {
        "action": "calendar_connections.disconnect",
        "provider": GOOGLE_PROVIDER,
        "connection_id": disconnected["id"],
        "disconnected": True,
        "connection": _public_connection(disconnected),
    }


def default_transport(method: str, url: str, request: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Small JSON HTTP transport used by production OAuth calls."""
    headers = {str(key): str(value) for key, value in dict(request.get("headers") or {}).items()}
    data = request.get("data")
    encoded_data: bytes | None = None
    if data is None and "json" in request:
        encoded_data = json.dumps(request["json"]).encode("utf-8")
    elif isinstance(data, dict):
        encoded_data = urlencode(data).encode("utf-8")
    elif isinstance(data, str):
        encoded_data = data.encode("utf-8")
    elif isinstance(data, bytes):
        encoded_data = data
    req = Request(url, data=encoded_data, headers=headers, method=method.upper())
    try:
        with urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
            return int(response.status), payload if isinstance(payload, dict) else {}
    except HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        return int(error.code), payload if isinstance(payload, dict) else {}
    except URLError as error:
        raise CalendarOAuthError("oauth_provider_unavailable", "Google OAuth is currently unavailable.") from error


def _exchange_code(http: HttpTransport, *, code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict[str, Any]:
    status, payload = http(
        "POST",
        GOOGLE_TOKEN_URL,
        {
            "headers": {"content-type": "application/x-www-form-urlencoded"},
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
        error_code = str(payload.get("error") or "oauth_exchange_failed")
        raise CalendarOAuthError("oauth_exchange_failed", f"Google OAuth token exchange failed: {error_code}.")
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise CalendarOAuthError("oauth_exchange_failed", "Google OAuth token exchange did not return an access token.")
    return payload


def _revoke_refresh_token(
    *,
    app_secrets: dict[str, str] | None,
    app_secret_errors: list[dict[str, Any]] | None,
    transport: HttpTransport | None,
) -> None:
    refresh_token = _required_app_secret(
        app_secrets,
        app_secret_errors,
        GOOGLE_REFRESH_TOKEN_LOGICAL_NAME,
        detail="Google Calendar refresh token is unavailable through Core Secrets.",
    )
    http = transport or default_transport
    status, payload = http(
        "POST",
        GOOGLE_REVOKE_URL,
        {
            "headers": {"content-type": "application/x-www-form-urlencoded"},
            "data": {"token": refresh_token},
        },
    )
    if status >= 400:
        error_code = str(payload.get("error") or "token_revoke_failed") if isinstance(payload, dict) else "token_revoke_failed"
        raise CalendarOAuthError("token_revoke_failed", f"Google Calendar token revoke failed: {error_code}.", status_code=502)


def _fetch_profile(http: HttpTransport, access_token: Any) -> dict[str, Any]:
    token = str(access_token or "").strip()
    if not token:
        return {}
    status, payload = http("GET", GOOGLE_PROFILE_URL, {"headers": {"authorization": f"Bearer {token}"}})
    if status >= 400 or not isinstance(payload, dict):
        return {}
    return payload


def _requested_scopes(value: Any) -> list[str]:
    if isinstance(value, list):
        scopes = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str) and value.strip():
        scopes = [item.strip() for item in value.split() if item.strip()]
    else:
        scopes = list(DEFAULT_SCOPES)
    return _dedupe([*REQUIRED_GOOGLE_CALENDAR_SCOPES, *scopes])


def _token_scopes(payload: dict[str, Any]) -> list[str]:
    return _dedupe(str(payload.get("scope") or "").split())


def _validate_calendar_scope(scopes: list[str]) -> None:
    missing = [scope for scope in REQUIRED_GOOGLE_CALENDAR_SCOPES if scope not in scopes]
    if missing:
        raise CalendarOAuthError(
            "missing_calendar_scope",
            f"Google OAuth response did not grant required Calendar scopes: {', '.join(missing)}.",
        )


def _required_app_secret(
    app_secrets: dict[str, str] | None,
    app_secret_errors: list[dict[str, Any]] | None,
    logical_name: str,
    *,
    detail: str,
) -> str:
    if logical_name in _secret_error_names(app_secret_errors):
        raise CalendarOAuthError("missing_secret_grant", detail, status_code=403)
    value = str((app_secrets or {}).get(logical_name) or "").strip()
    if not value:
        raise CalendarOAuthError("missing_secret_grant", detail, status_code=403)
    return value


def _secret_error_names(app_secret_errors: list[dict[str, Any]] | None) -> list[str]:
    names: list[str] = []
    for item in app_secret_errors or []:
        if not isinstance(item, dict):
            continue
        logical_name = str(item.get("logical_name") or "").strip().lower()
        if logical_name and logical_name not in names:
            names.append(logical_name)
    return names


def _missing_secret_names(app_secrets: dict[str, str], names: list[str]) -> list[str]:
    return [name for name in names if not str(app_secrets.get(name) or "").strip()]


def _require_provider(body: dict[str, Any]) -> None:
    provider = str(body.get("provider") or GOOGLE_PROVIDER).strip().lower()
    if provider != GOOGLE_PROVIDER:
        raise CalendarOAuthError("unsupported_provider", "Calendar OAuth currently supports provider `google` only.")


def _redirect_uri(body: dict[str, Any], *, app_id: str) -> str:
    return clean_string(
        body.get("redirect_uri") or body.get("redirectUri") or f"/apps/{app_id}/oauth/callback",
        "redirect_uri",
        required=True,
        max_length=2048,
    )


def _completion_redirect_uri(body: dict[str, Any], *, app_id: str, state_record: dict[str, Any]) -> str:
    external_refs = state_record.get("external_refs") if isinstance(state_record.get("external_refs"), dict) else {}
    stored = str(external_refs.get("oauth_redirect_uri") or "").strip()
    supplied = str(body.get("redirect_uri") or body.get("redirectUri") or "").strip()
    redirect_uri = supplied or stored or f"/apps/{app_id}/oauth/callback"
    if stored and supplied and supplied != stored:
        raise CalendarOAuthError("invalid_oauth_callback", "OAuth callback redirect_uri does not match the started flow.")
    return clean_string(redirect_uri, "redirect_uri", required=True, max_length=2048)


def _pending_connection_for_state(state: dict[str, Any], state_value: str, *, now: datetime) -> dict[str, Any]:
    state_hash = _state_hash(state_value)
    expired_match = False
    for connection in state.get("connections", []):
        if not isinstance(connection, dict) or connection.get("status") != "pending":
            continue
        external_refs = connection.get("external_refs") if isinstance(connection.get("external_refs"), dict) else {}
        if external_refs.get("oauth_state_hash") != state_hash:
            continue
        expires_at = _optional_datetime(external_refs.get("oauth_state_expires_at"))
        if expires_at is not None and expires_at <= now:
            expired_match = True
            continue
        return connection
    if expired_match:
        raise CalendarOAuthError("expired_oauth_state", "OAuth state has expired. Start Google Calendar OAuth again.")
    raise CalendarOAuthError("invalid_oauth_callback", "OAuth callback state is invalid.")


def _connection_by_id(state: dict[str, Any], connection_id: str) -> dict[str, Any]:
    for item in state.get("connections", []):
        if not isinstance(item, dict):
            continue
        connection = normalize_connection(item)
        if connection["id"] == connection_id:
            return connection
    raise CalendarOAuthError("calendar_connection_not_found", f"Calendar connection `{connection_id}` was not found.", status_code=404)


def _reconnect_target_connection(
    state: dict[str, Any],
    *,
    state_record: dict[str, Any],
    profile: dict[str, Any],
    account_id: str,
) -> dict[str, Any] | None:
    subject = str(profile.get("id") or profile.get("sub") or "").strip()
    account_keys = {
        value.casefold()
        for value in [
            account_id,
            str(profile.get("email") or ""),
        ]
        if value.strip()
    }
    if not subject and not account_keys:
        return None
    pending_id = _connection_record_id(state_record)
    candidates: list[dict[str, Any]] = []
    for item in state.get("connections", []):
        if not isinstance(item, dict):
            continue
        connection = normalize_connection(item)
        if (
            connection["id"] == pending_id
            or connection["provider"] != GOOGLE_PROVIDER
            or connection["status"] == "pending"
        ):
            continue
        if _matches_google_account(connection, subject=subject, account_keys=account_keys):
            candidates.append(connection)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: _reconnect_sort_key(state, item), reverse=True)[0]


def _matches_google_account(connection: dict[str, Any], *, subject: str, account_keys: set[str]) -> bool:
    external_refs = connection.get("external_refs") if isinstance(connection.get("external_refs"), dict) else {}
    existing_subject = str(external_refs.get("google_subject") or "").strip()
    if subject and existing_subject == subject:
        return True
    existing_account = str(connection.get("account_id") or "").strip().casefold()
    return bool(existing_account and existing_account in account_keys)


def _reconnect_sort_key(state: dict[str, Any], connection: dict[str, Any]) -> tuple[int, int, str]:
    status_rank = {"connected": 2, "error": 1, "disabled": 0}.get(str(connection.get("status") or ""), 0)
    recency = str(connection.get("updated_at") or connection.get("created_at") or "")
    return (_connection_usage_count(state, connection["id"]), status_rank, recency)


def _connection_usage_count(state: dict[str, Any], connection_id: str) -> int:
    count = 0
    for event in state.get("events", []):
        if not isinstance(event, dict):
            continue
        refs = event.get("external_refs") if isinstance(event.get("external_refs"), dict) else {}
        if str(refs.get("calendar_connection_id") or "").strip() == connection_id:
            count += 1
    for calendar in state.get("calendars", []):
        if isinstance(calendar, dict) and str(calendar.get("connection_id") or "").strip() == connection_id:
            count += 1
    for cursor in state.get("sync_state", []):
        if isinstance(cursor, dict) and str(cursor.get("connection_id") or "").strip() == connection_id:
            count += 1
    return count


def _replace_connection(state: dict[str, Any], connection: dict[str, Any]) -> dict[str, Any]:
    connection_id = str(connection.get("id") or "").strip()
    remaining = [
        item
        for item in state.get("connections", [])
        if isinstance(item, dict) and str(item.get("id") or item.get("connection_id") or item.get("connectionId") or "").strip() != connection_id
    ]
    state["connections"] = [*remaining, normalize_connection(connection)]
    return state


def _replace_completed_connection(
    state: dict[str, Any],
    *,
    state_record: dict[str, Any],
    connection: dict[str, Any],
) -> dict[str, Any]:
    completed_id = _connection_record_id(connection)
    pending_id = _connection_record_id(state_record)
    replaced_ids = {completed_id, pending_id}
    state["connections"] = [
        item
        for item in state.get("connections", [])
        if isinstance(item, dict) and _connection_record_id(item) not in replaced_ids
    ]
    state["connections"].append(normalize_connection(connection))
    return state


def _connection_record_id(connection: dict[str, Any]) -> str:
    return str(connection.get("id") or connection.get("connection_id") or connection.get("connectionId") or "").strip()


def _prune_expired_pending_connections(data_root) -> dict[str, Any]:
    now = datetime.now(UTC)

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        state["connections"] = [
            item
            for item in state.get("connections", [])
            if not _is_expired_pending_connection(item, now=now)
        ]
        return state

    update_state(data_root, updater)
    return read_state(data_root)


def _is_expired_pending_connection(connection: dict[str, Any], *, now: datetime) -> bool:
    if not isinstance(connection, dict) or connection.get("status") != "pending":
        return False
    external_refs = connection.get("external_refs") if isinstance(connection.get("external_refs"), dict) else {}
    expires_at = _optional_datetime(external_refs.get("oauth_state_expires_at"))
    return expires_at is not None and expires_at <= now


def _active_connections(connections: list[Any]) -> list[dict[str, Any]]:
    return [item for item in connections if isinstance(item, dict) and item.get("status") == "connected"]


def _connected_external_refs(state_record: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    external_refs = state_record.get("external_refs") if isinstance(state_record.get("external_refs"), dict) else {}
    result = {
        key: value
        for key, value in external_refs.items()
        if key not in {"oauth_state_hash", "oauth_state_expires_at", "oauth_redirect_uri", "disconnected_at"}
    }
    subject = str(profile.get("id") or profile.get("sub") or "").strip()
    if subject:
        result["google_subject"] = subject[:MAX_PROVIDER_ID_LENGTH]
    return result


def _public_connection(connection: dict[str, Any]) -> dict[str, Any]:
    public = normalize_connection(connection)
    external_refs = dict(public.get("external_refs") or {})
    for key in ("oauth_state_hash", "oauth_state_expires_at", "oauth_redirect_uri"):
        external_refs.pop(key, None)
    public["external_refs"] = external_refs
    return public


def _account_identity(body: dict[str, Any], profile: dict[str, Any], state_record: dict[str, Any]) -> tuple[str, str]:
    account_id = clean_string(
        body.get("account_id")
        or body.get("accountId")
        or profile.get("email")
        or profile.get("id")
        or profile.get("sub")
        or state_record.get("id"),
        "account_id",
        required=True,
        max_length=MAX_PROVIDER_ID_LENGTH,
    )
    account_label = clean_string(
        body.get("account_label") or body.get("accountLabel") or profile.get("name") or profile.get("email") or account_id,
        "account_label",
        required=True,
        max_length=MAX_PROVIDER_ID_LENGTH,
    )
    return account_id, account_label


def _required_callback_string(value: Any, field: str) -> str:
    try:
        return clean_string(value, field, required=True, max_length=MAX_PROVIDER_ID_LENGTH)
    except ValueError as error:
        raise CalendarOAuthError("invalid_oauth_callback", f"OAuth callback `{field}` is required.") from error


def _optional_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return iso_time(value, "oauth_state_expires_at")
    except ValueError:
        return None


def _state_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
