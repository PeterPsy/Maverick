"""Google OAuth configuration, capability scopes and guarded API transport."""

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, unquote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from core.secrets.errors import SecretError
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import resolve_secret_for_runtime


PREFIX = "https://www.googleapis.com/auth/"
SERVICES = {
    "calendar": {"label": "Calendar", "scopes": [PREFIX + "calendar.events", PREFIX + "calendar.calendarlist.readonly"]},
    "gmail": {"label": "Gmail", "scopes": [PREFIX + "gmail.modify", PREFIX + "gmail.send"]},
    "drive": {"label": "Drive", "scopes": [PREFIX + "drive"]},
}
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
CALLBACK_PATH = "/api/auth/google/callback"
MAX_RESPONSE_BYTES = 40 * 1024 * 1024


class AccountError(ValueError):
    def __init__(self, code, *, status=400):
        self.code, self.status = code, status
        super().__init__(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def provider_request(request, *, timeout=30, max_bytes=MAX_RESPONSE_BYTES):
    """Never follow provider redirects with an attached credential."""
    try:
        response = build_opener(NoRedirect()).open(request, timeout=timeout)
    except HTTPError as error:
        response = error
    except (URLError, TimeoutError):
        raise AccountError("google_unavailable", status=502) from None
    with response:
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise AccountError("google_response_too_large", status=502)
        return response.code, dict(response.headers.items()), data


def json_request(url, *, data=None, headers=None):
    headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    status, _, raw = provider_request(Request(url, data=urlencode(data).encode() if data is not None else None, headers=headers), max_bytes=1024 * 1024)
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise AccountError("google_invalid_response", status=502) from None
    if not isinstance(payload, dict):
        raise AccountError("google_invalid_response", status=502)
    if status >= 400:
        raise AccountError("google_reconnect_required" if payload.get("error") == "invalid_grant" else "google_request_failed", status=401 if payload.get("error") == "invalid_grant" else 502)
    return payload


def credential_refs():
    return (
        os.environ.get("LOOPINO_GOOGLE_CLIENT_ID_REF", "platform:secret-alias/google-oauth-client-id"),
        os.environ.get("LOOPINO_GOOGLE_CLIENT_SECRET_REF", "platform:secret-alias/google-oauth-client-secret"),
    )


def secret_value(store, ref):
    return resolve_secret_for_runtime(store, context=SecretResolutionContext(
        workspace_id=None, operator_request=True, allow_unbound_secret_refs=True, platform_delivery=True,
    ), secret_ref=ref).value


def credentials(store):
    try:
        return tuple(secret_value(store, ref) for ref in credential_refs())
    except SecretError:
        raise AccountError("google_not_configured", status=503) from None


def redirect_uri():
    uri = os.environ.get("LOOPINO_GOOGLE_REDIRECT_URI", "").strip()
    parsed = urlsplit(uri)
    if (parsed.path != CALLBACK_PATH or not parsed.hostname or parsed.query or parsed.fragment
            or parsed.username or parsed.password or parsed.scheme not in {"https", "http"}
            or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"} and not parsed.hostname.endswith(".localhost"))):
        raise AccountError("google_not_configured", status=503)
    return uri


def available_services(scopes):
    granted = set(scopes)
    return [key for key, value in SERVICES.items() if set(value["scopes"]) <= granted]


def validate_services(value):
    if not isinstance(value, list) or any(not isinstance(item, str) or item not in SERVICES for item in value):
        raise AccountError("invalid_google_services")
    return sorted(set(value))


def allowed_api_request(services, method, url):
    """Enforce API capability boundaries even though Google tokens combine scopes."""
    parsed = urlsplit(url)
    path = parsed.path
    if (parsed.scheme != "https" or parsed.port not in {None, 443} or parsed.username
            or parsed.password or parsed.fragment or "\\" in path
            or any(part in {".", ".."} for part in unquote(path).split("/"))):
        return False
    if method not in {"GET", "HEAD", "POST", "PATCH", "PUT", "DELETE"}:
        return False
    host = parsed.hostname
    if "calendar" in services and host == "www.googleapis.com":
        if path == "/calendar/v3/users/me/calendarList" or path.startswith("/calendar/v3/users/me/calendarList/"):
            return method in {"GET", "HEAD"}
        if re.fullmatch(r"/calendar/v3/calendars/[^/]+/events(?:/[^/]+(?:/(?:instances|move))?)?", path):
            return True
    if "gmail" in services and host in {"gmail.googleapis.com", "www.googleapis.com"}:
        if re.fullmatch(r"/gmail/v1/users/me/messages/[^/]+/attachments/[^/]+", path):
            return method in {"GET", "HEAD"}
        return bool(re.fullmatch(r"/gmail/v1/users/me/(?:profile|threads|messages|labels|drafts|history)(?:/[^/]+){0,2}", path))
    if "drive" in services and host in {"www.googleapis.com", "upload.googleapis.com", "content.googleapis.com"}:
        return bool(re.fullmatch(r"/(?:upload/|download/)?drive/v3/(?:files|changes|about|drives)(?:/[^/]+){0,2}", path))
    return False
