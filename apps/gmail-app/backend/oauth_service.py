"""Google OAuth helpers for Gmail App."""

from __future__ import annotations

import json
import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from errors import GmailConnectionError, GmailAppValidationError

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def authorization_url(body: dict[str, Any]) -> dict[str, Any]:
    client_id = required(body, "client_id")
    redirect_uri = required(body, "redirect_uri")
    code_verifier = str(body.get("code_verifier") or "").strip() or secrets.token_urlsafe(48)
    code_challenge = str(body.get("code_challenge") or "").strip() or pkce_challenge(code_verifier)
    state = str(body.get("state") or "").strip() or secrets.token_urlsafe(24)
    scopes = body.get("scopes") if isinstance(body.get("scopes"), list) else DEFAULT_SCOPES
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(str(scope) for scope in scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent select_account",
            **({"login_hint": str(body["login_hint"]).strip()} if str(body.get("login_hint") or "").strip() else {}),
        }
    )
    return {"authorization_url": f"{GOOGLE_AUTH_URL}?{query}", "scopes": scopes, "state": state, "code_verifier": code_verifier}


def exchange_code(body: dict[str, Any]) -> dict[str, Any]:
    if body.get("mock_token"):
        token = body["mock_token"] if isinstance(body["mock_token"], dict) else {}
        return {
            "token": safe_token_payload(token),
            "token_secret": token_secret_payload(
                token,
                client_id=str(body.get("client_id") or ""),
                client_secret=str(body.get("client_secret") or ""),
            ),
            "account": {"email": str(body.get("mock_email") or "user@example.com"), "messages_total": 0, "threads_total": 0},
        }
    client_id = required(body, "client_id")
    client_secret = required(body, "client_secret")
    code = required(body, "code")
    redirect_uri = required(body, "redirect_uri")
    code_verifier = required(body, "code_verifier")
    payload = post_form(
        GOOGLE_TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    if not payload.get("access_token"):
        raise GmailConnectionError("Google token response did not include an access token.")
    profile = gmail_profile(str(payload["access_token"]))
    return {"token": safe_token_payload(payload), "token_secret": token_secret_payload(payload, client_id=client_id, client_secret=client_secret), "account": profile}


def refresh_access_token(*, client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any]:
    """Use a stored refresh token to mint a short-lived Gmail access token."""
    if not refresh_token:
        raise GmailConnectionError("Stored Gmail refresh token is missing.")
    payload = post_form(
        GOOGLE_TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    if not payload.get("access_token"):
        raise GmailConnectionError("Google refresh response did not include an access token.")
    return safe_token_payload(payload)


def gmail_profile(access_token: str) -> dict[str, Any]:
    request = Request(
        GMAIL_PROFILE_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as error:  # pragma: no cover - network path
        raise GmailConnectionError(f"Gmail profile request failed: {error}") from error
    return {
        "email": str(payload.get("emailAddress") or ""),
        "messages_total": int(payload.get("messagesTotal") or 0),
        "threads_total": int(payload.get("threadsTotal") or 0),
    }


def post_form(url: str, form: dict[str, str]) -> dict[str, Any]:
    encoded = urlencode(form).encode("utf-8")
    request = Request(
        url,
        data=encoded,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except Exception as error:  # pragma: no cover - network path
        raise GmailConnectionError(f"Google token exchange failed: {error}") from error


def safe_token_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "access_token": str(payload.get("access_token") or ""),
        "expires_in": int(payload.get("expires_in") or 0),
        "scope": str(payload.get("scope") or ""),
        "token_type": str(payload.get("token_type") or "Bearer"),
        "has_refresh_token": bool(payload.get("refresh_token")),
    }


def token_secret_payload(payload: dict[str, Any], *, client_id: str, client_secret: str) -> dict[str, Any]:
    """Build the raw app secret value stored by the platform, not returned to the browser."""
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": str(payload.get("refresh_token") or ""),
        "access_token": str(payload.get("access_token") or ""),
        "scope": str(payload.get("scope") or ""),
        "token_type": str(payload.get("token_type") or "Bearer"),
    }


def required(body: dict[str, Any], key: str) -> str:
    value = str(body.get(key) or "").strip()
    if not value:
        raise GmailAppValidationError(f"{key} is required.")
    return value


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
