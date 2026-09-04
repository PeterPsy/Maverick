"""Session-bound discovery tokens and their classification projection."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets

from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_result_classification import (
    RuntimeToolClassificationProjection,
)


_DISCOVERY_TOKEN_KEY = secrets.token_bytes(32)
_DISCOVERY_TOKEN_DOMAIN = b"maverick.runtime-tool-discovery.v1\0"


def issue_discovery_token(
    *,
    kind: str,
    target: str,
    session_id: str,
    registry_revision: str,
) -> str:
    """Issue an opaque invocation token for one exact discovery snapshot."""
    raw = json.dumps(
        {
            "kind": kind,
            "target": target,
            "session_id": session_id,
            "registry_revision": registry_revision,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(
        _DISCOVERY_TOKEN_KEY,
        _DISCOVERY_TOKEN_DOMAIN + raw,
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(signature + raw).decode("ascii").rstrip("=")


def validate_discovery_token(
    value: object,
    *,
    kind: str,
    target: str,
    session_id: str,
    registry_revision: str,
) -> None:
    """Require a token issued for the exact kind, target, session, and registry."""
    if not isinstance(value, str) or not value:
        raise RuntimeToolError("tool_discovery_required")
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        signature, raw = decoded[:32], decoded[32:]
        expected_signature = hmac.new(
            _DISCOVERY_TOKEN_KEY,
            _DISCOVERY_TOKEN_DOMAIN + raw,
            hashlib.sha256,
        ).digest()
        payload = json.loads(raw)
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeToolError("tool_discovery_token_invalid") from error
    if (
        not hmac.compare_digest(signature, expected_signature)
        or payload
        != {
            "kind": kind,
            "target": target,
            "session_id": session_id,
            "registry_revision": registry_revision,
        }
    ):
        raise RuntimeToolError("tool_discovery_token_invalid")


def authenticated_discovery_classification_projection(
    handle: str,
    payload: dict[str, object],
    *,
    session_id: str,
) -> RuntimeToolClassificationProjection | None:
    """Project only HMAC-authenticated tokens and the exact registry revision."""
    collection, identity_field, kind = (
        ("commands", "command_id", "cli")
        if handle == "core-capability:cli.list"
        else ("tools", "tool_name", "mcp")
    )
    registry_revision = payload.get("registry_revision")
    if (
        handle not in {
            "core-capability:cli.list",
            "core-capability:mcp.list",
        }
        or not _sha256(registry_revision)
        or payload.get("discovery_first") is not True
        or not isinstance(payload.get(collection), list)
    ):
        return None
    omitted_paths: list[tuple[str | int, ...]] = [("registry_revision",)]
    try:
        for index, raw_item in enumerate(payload[collection]):
            if not isinstance(raw_item, dict):
                return None
            identity = raw_item.get(identity_field)
            if not isinstance(identity, str) or not identity:
                return None
            validate_discovery_token(
                raw_item.get("invocation_token"),
                kind=kind,
                target=identity,
                session_id=session_id,
                registry_revision=registry_revision,
            )
            omitted_paths.append((collection, index, "invocation_token"))
        return RuntimeToolClassificationProjection.bind(
            payload,
            omitted_paths=tuple(omitted_paths),
            content_type="text/plain",
        )
    except RuntimeToolError:
        return None


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "authenticated_discovery_classification_projection",
    "issue_discovery_token",
    "validate_discovery_token",
]
