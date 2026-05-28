"""Google Calendar HTTP provider primitives."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from constants import GOOGLE_REFRESH_TOKEN_LOGICAL_NAME
from google_oauth import CalendarOAuthError, HttpTransport, default_transport


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
GOOGLE_OAUTH_CLIENT_ID_LOGICAL_NAME = "google-oauth-client-id"
GOOGLE_OAUTH_CLIENT_SECRET_LOGICAL_NAME = "google-oauth-client-secret"


class GoogleSyncTokenGone(CalendarOAuthError):
    """Raised when Google reports that an incremental sync token is stale."""

    def __init__(self) -> None:
        super().__init__(
            "google_sync_token_gone",
            "Google Calendar incremental sync token expired and requires a full resync.",
            status_code=410,
        )


def refresh_access_token(
    *,
    app_secrets: dict[str, str] | None,
    app_secret_errors: list[dict[str, Any]] | None = None,
    transport: HttpTransport | None = None,
) -> str:
    """Exchange the resource-scoped refresh token for a short-lived access token."""
    client_id = _required_secret(
        app_secrets,
        app_secret_errors,
        GOOGLE_OAUTH_CLIENT_ID_LOGICAL_NAME,
        detail="Google OAuth client id is unavailable through Core Secrets.",
    )
    client_secret = _required_secret(
        app_secrets,
        app_secret_errors,
        GOOGLE_OAUTH_CLIENT_SECRET_LOGICAL_NAME,
        detail="Google OAuth client secret is unavailable through Core Secrets.",
    )
    refresh_token = _required_secret(
        app_secrets,
        app_secret_errors,
        GOOGLE_REFRESH_TOKEN_LOGICAL_NAME,
        detail="Google Calendar refresh token is unavailable through Core Secrets.",
    )
    http = transport or default_transport
    status, payload = http(
        "POST",
        GOOGLE_TOKEN_URL,
        {
            "headers": {"content-type": "application/x-www-form-urlencoded"},
            "data": {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        },
    )
    if status >= 400:
        error_code = str(payload.get("error") or "token_refresh_failed") if isinstance(payload, dict) else "token_refresh_failed"
        raise CalendarOAuthError("token_refresh_failed", f"Google Calendar token refresh failed: {error_code}.", status_code=502)
    access_token = str(payload.get("access_token") or "").strip() if isinstance(payload, dict) else ""
    if not access_token:
        raise CalendarOAuthError("token_refresh_failed", "Google Calendar token refresh did not return an access token.", status_code=502)
    return access_token


def list_calendar_list(
    *,
    access_token: str,
    page_token: str = "",
    max_results: int = 250,
    transport: HttpTransport | None = None,
) -> dict[str, Any]:
    """Call calendarList.list for the authenticated Google account."""
    query = {"maxResults": str(max_results)}
    if page_token:
        query["pageToken"] = page_token
    return _google_get(
        f"{GOOGLE_CALENDAR_API_BASE}/users/me/calendarList?{urlencode(query)}",
        access_token=access_token,
        transport=transport,
    )


def list_events(
    *,
    access_token: str,
    calendar_id: str,
    page_token: str = "",
    sync_token: str = "",
    max_results: int = 250,
    transport: HttpTransport | None = None,
) -> dict[str, Any]:
    """Call events.list for one calendar using either full or incremental sync."""
    query = {
        "maxResults": str(max_results),
        "showDeleted": "true",
    }
    if page_token:
        query["pageToken"] = page_token
    if sync_token:
        query["syncToken"] = sync_token
    encoded_calendar_id = quote(calendar_id, safe="")
    return _google_get(
        f"{GOOGLE_CALENDAR_API_BASE}/calendars/{encoded_calendar_id}/events?{urlencode(query)}",
        access_token=access_token,
        transport=transport,
    )


def insert_event(
    *,
    access_token: str,
    calendar_id: str,
    event: dict[str, Any],
    transport: HttpTransport | None = None,
) -> dict[str, Any]:
    """Call events.insert for one Google Calendar event."""
    encoded_calendar_id = quote(calendar_id, safe="")
    return _google_json_request(
        "POST",
        f"{GOOGLE_CALENDAR_API_BASE}/calendars/{encoded_calendar_id}/events",
        access_token=access_token,
        transport=transport,
        body=event,
    )


def patch_event(
    *,
    access_token: str,
    calendar_id: str,
    event_id: str,
    event: dict[str, Any],
    etag: str = "",
    transport: HttpTransport | None = None,
) -> dict[str, Any]:
    """Call events.patch for one Google Calendar event."""
    encoded_calendar_id = quote(calendar_id, safe="")
    encoded_event_id = quote(event_id, safe="")
    return _google_json_request(
        "PATCH",
        f"{GOOGLE_CALENDAR_API_BASE}/calendars/{encoded_calendar_id}/events/{encoded_event_id}",
        access_token=access_token,
        transport=transport,
        body=event,
        etag=etag,
    )


def delete_event(
    *,
    access_token: str,
    calendar_id: str,
    event_id: str,
    etag: str = "",
    transport: HttpTransport | None = None,
) -> dict[str, Any]:
    """Call events.delete for one Google Calendar event."""
    encoded_calendar_id = quote(calendar_id, safe="")
    encoded_event_id = quote(event_id, safe="")
    http = transport or default_transport
    headers = _auth_headers(access_token, etag=etag)
    status, payload = http(
        "DELETE",
        f"{GOOGLE_CALENDAR_API_BASE}/calendars/{encoded_calendar_id}/events/{encoded_event_id}",
        {"headers": headers},
    )
    if status in {204, 404, 410}:
        return {"deleted": True, "remote_missing": status in {404, 410}}
    _raise_google_error(status, payload)
    return {"deleted": True}


def _google_get(url: str, *, access_token: str, transport: HttpTransport | None) -> dict[str, Any]:
    http = transport or default_transport
    status, payload = http("GET", url, {"headers": _auth_headers(access_token)})
    if status == 410:
        raise GoogleSyncTokenGone()
    _raise_google_error(status, payload)
    if not isinstance(payload, dict):
        raise CalendarOAuthError("google_calendar_request_failed", "Google Calendar API response was not a JSON object.", status_code=502)
    return payload


def _google_json_request(
    method: str,
    url: str,
    *,
    access_token: str,
    transport: HttpTransport | None,
    body: dict[str, Any],
    etag: str = "",
) -> dict[str, Any]:
    http = transport or default_transport
    status, payload = http(
        method,
        url,
        {
            "headers": _auth_headers(access_token, etag=etag, content_type="application/json"),
            "json": body,
        },
    )
    _raise_google_error(status, payload)
    if not isinstance(payload, dict):
        raise CalendarOAuthError("google_calendar_request_failed", "Google Calendar API response was not a JSON object.", status_code=502)
    return payload


def _auth_headers(access_token: str, *, etag: str = "", content_type: str = "") -> dict[str, str]:
    headers = {"authorization": f"Bearer {access_token}"}
    if content_type:
        headers["content-type"] = content_type
    if etag:
        headers["if-match"] = etag
    return headers


def _raise_google_error(status: int, payload: Any) -> None:
    if status < 400:
        return
    error_code = _google_error_code(payload)
    if status == 412:
        raise CalendarOAuthError(
            "google_calendar_revision_conflict",
            f"Google Calendar rejected the stale event revision: {error_code}.",
            status_code=409,
        )
    if status == 401:
        raise CalendarOAuthError(
            "google_calendar_unauthorized",
            f"Google Calendar authorization failed: {error_code}.",
            status_code=401,
        )
    if status == 403:
        raise CalendarOAuthError(
            "google_calendar_forbidden",
            f"Google Calendar denied the requested operation: {error_code}.",
            status_code=403,
        )
    if status == 404:
        raise CalendarOAuthError("google_calendar_event_not_found", "Google Calendar event was not found.", status_code=404)
    raise CalendarOAuthError("google_calendar_request_failed", f"Google Calendar API request failed: {error_code}.", status_code=502)


def _required_secret(
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


def _google_error_code(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "request_failed"
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("status") or error.get("message") or error.get("code") or "request_failed")
    return str(error or "request_failed")
