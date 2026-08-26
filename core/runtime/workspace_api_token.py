"""Workspace-scoped API tokens issued to runtime sessions."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from core.execution_policy.models import ExecutionMode
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.runtime_session import RuntimeApiTokenRecord
from core.secrets.bootstrap import resolve_bootstrap_secret

if TYPE_CHECKING:
    from core.runtime.store import RuntimeStore


TOKEN_VERSION = "mvr3rt2"
DEFAULT_TOKEN_TTL_SECONDS = 60 * 60
RuntimeApiTokenClaims = dict[str, str | int]


def issue_workspace_api_token(
    *,
    workspace_id: str,
    runtime_session_id: str,
    effective_mode: str = "sandbox",
    ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
    now: datetime | None = None,
) -> str:
    """Build a signed bearer token for one runtime session."""
    timestamp = int((now or datetime.now(tz=UTC)).timestamp())
    payload = {
        "version": TOKEN_VERSION,
        "workspace_id": workspace_id,
        "runtime_session_id": runtime_session_id,
        "mode": effective_mode,
        "token_id": str(uuid4()),
        "issued_at": timestamp,
        "expires_at": timestamp + max(1, int(ttl_seconds)),
    }
    encoded = _base64_url(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _sign(encoded)
    return f"{encoded}.{signature}"


def verify_workspace_api_token(token: str, *, now: datetime | None = None) -> RuntimeApiTokenClaims | None:
    """Return token claims when the signature and shape are valid."""
    encoded, separator, signature = token.partition(".")
    if not separator or not encoded or not signature:
        return None
    expected = _sign(encoded)
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        raw = base64.urlsafe_b64decode(_pad_base64(encoded)).decode("utf-8")
        payload: Any = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != TOKEN_VERSION:
        return None
    workspace_id = payload.get("workspace_id")
    runtime_session_id = payload.get("runtime_session_id")
    if not isinstance(workspace_id, str) or not workspace_id:
        return None
    if not isinstance(runtime_session_id, str) or not runtime_session_id:
        return None
    mode = payload.get("mode")
    token_id = payload.get("token_id")
    issued_at = payload.get("issued_at")
    expires_at = payload.get("expires_at")
    if mode not in {"sandbox", "full-access"}:
        return None
    if not isinstance(token_id, str) or not token_id:
        return None
    if not isinstance(issued_at, int):
        return None
    if not isinstance(expires_at, int):
        return None
    if issued_at >= expires_at:
        return None
    if expires_at <= int((now or datetime.now(tz=UTC)).timestamp()):
        return None
    return {
        "workspace_id": workspace_id,
        "runtime_session_id": runtime_session_id,
        "mode": mode,
        "token_id": token_id,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }


def runtime_api_token_record_from_claims(claims: RuntimeApiTokenClaims) -> RuntimeApiTokenRecord:
    """Build the persisted lifecycle record represented by verified token claims."""
    mode = str(claims["mode"])
    if mode not in {"sandbox", "full-access"}:
        raise ValueError("Runtime API token mode must be sandbox or full-access.")
    return RuntimeApiTokenRecord(
        token_id=str(claims["token_id"]),
        session_id=str(claims["runtime_session_id"]),
        workspace_id=str(claims["workspace_id"]),
        mode=cast(ExecutionMode, mode),
        status="active",
        issued_at=datetime.fromtimestamp(int(claims["issued_at"]), tz=UTC),
        expires_at=datetime.fromtimestamp(int(claims["expires_at"]), tz=UTC),
    )


def register_workspace_api_token(
    store: RuntimeStore,
    token: str,
    *,
    now: datetime | None = None,
) -> RuntimeApiTokenRecord | None:
    """Persist a newly issued runtime API token so later calls can be revoked."""
    claims = verify_workspace_api_token(token, now=now)
    if claims is None:
        return None
    return store.save_api_token(runtime_api_token_record_from_claims(claims))


def validate_workspace_api_token_lifecycle(
    store: RuntimeStore,
    token: str,
    *,
    now: datetime | None = None,
) -> tuple[RuntimeApiTokenClaims | None, str | None]:
    """Verify token crypto plus persisted lifecycle status."""
    timestamp = now or datetime.now(tz=UTC)
    claims = verify_workspace_api_token(token, now=timestamp)
    if claims is None:
        return None, "authentication_required"
    record = store.get_api_token(str(claims["token_id"]))
    if record is None:
        return None, "runtime_token_unregistered"
    if record.status != "active":
        return None, "runtime_token_revoked"
    if record.expires_at <= timestamp:
        return None, "runtime_token_expired"
    if (
        record.session_id != str(claims["runtime_session_id"])
        or record.workspace_id != str(claims["workspace_id"])
        or record.mode != str(claims["mode"])
    ):
        return None, "runtime_token_mismatch"
    try:
        session = store.get_session(record.session_id)
    except RuntimeSessionNotFoundError:
        return None, "runtime_session_unavailable"
    if session.workspace_id != record.workspace_id:
        return None, "runtime_token_mismatch"
    if session.status == "recovery_required":
        return None, "runtime_session_recovery_required"
    return claims, None


def _sign(encoded_payload: str) -> str:
    digest = hmac.new(_secret(), encoded_payload.encode("utf-8"), hashlib.sha256).digest()
    return _base64_url(digest)


def _secret() -> bytes:
    configured_ref = os.environ.get("MAVERICK_RUNTIME_API_SECRET_REF", "").strip()
    if configured_ref:
        return resolve_bootstrap_secret(configured_ref).encode("utf-8")
    configured = os.environ.get("MAVERICK_RUNTIME_API_SECRET", "").strip()
    if configured:
        return configured.encode("utf-8")
    if os.environ.get("MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS") == "1":
        return b"maverick-local-runtime-api"
    raise RuntimeError("MAVERICK_RUNTIME_API_SECRET_REF or MAVERICK_RUNTIME_API_SECRET is required.")


def _base64_url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _pad_base64(value: str) -> bytes:
    return (value + "=" * (-len(value) % 4)).encode("ascii")
