"""Opaque private payload boundary for tool arguments and results."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from threading import RLock
from typing import Protocol
from uuid import uuid4

from core.runtime.private_payload_models import (
    RuntimePrivatePayloadContext,
    RuntimePrivatePayloadError,
)
from core.runtime.private_payload_store import EncryptedRuntimePrivatePayloadStore
from core.runtime.tool_errors import RuntimeToolError


MAX_TOOL_PRIVATE_PAYLOAD_BYTES = 1_048_576
_DIGEST_DOMAIN = b"maverick.runtime.tool-arguments.v1\x00"


class RuntimeToolPrivatePayloadStore(Protocol):
    """Core-owned opaque storage; references convey no payload authority."""

    def put(self, *, workspace_id: str, session_id: str, payload: bytes) -> str: ...

    def read(self, *, workspace_id: str, session_id: str, private_ref: str) -> bytes: ...

    def delete(self, *, workspace_id: str, session_id: str, private_ref: str) -> bool: ...


@dataclass(frozen=True)
class _PrivatePayload:
    workspace_id: str
    session_id: str
    payload: bytes


class InMemoryRuntimeToolPrivatePayloadStore:
    """Process-local test implementation enforcing locator ownership."""

    def __init__(self, *, max_payload_bytes: int = MAX_TOOL_PRIVATE_PAYLOAD_BYTES) -> None:
        self._max_payload_bytes = max_payload_bytes
        self._records: dict[str, _PrivatePayload] = {}
        self._lock = RLock()

    def put(self, *, workspace_id: str, session_id: str, payload: bytes) -> str:
        if not payload or len(payload) > self._max_payload_bytes:
            raise RuntimeToolError("tool_private_payload_invalid")
        private_ref = f"tool-private:v1:{uuid4().hex}"
        with self._lock:
            self._records[private_ref] = _PrivatePayload(workspace_id, session_id, bytes(payload))
        return private_ref

    def read(self, *, workspace_id: str, session_id: str, private_ref: str) -> bytes:
        with self._lock:
            record = self._records.get(private_ref)
        if record is None or (record.workspace_id, record.session_id) != (workspace_id, session_id):
            raise RuntimeToolError("tool_private_payload_unavailable")
        return bytes(record.payload)

    def delete(self, *, workspace_id: str, session_id: str, private_ref: str) -> bool:
        with self._lock:
            record = self._records.get(private_ref)
            if record is None or (record.workspace_id, record.session_id) != (workspace_id, session_id):
                return False
            del self._records[private_ref]
        return True


class EncryptedRuntimeToolPrivatePayloadStore:
    """Restart-safe encrypted implementation sharing the Core private blob model."""

    def __init__(self, store: EncryptedRuntimePrivatePayloadStore) -> None:
        self._store = store

    def put(self, *, workspace_id: str, session_id: str, payload: bytes) -> str:
        try:
            return self._store.put(
                context=_tool_context(workspace_id, session_id),
                locator_prefix="tool-private",
                payload=payload,
                max_blob_bytes=MAX_TOOL_PRIVATE_PAYLOAD_BYTES,
                max_session_bytes=16 * MAX_TOOL_PRIVATE_PAYLOAD_BYTES,
            )
        except RuntimePrivatePayloadError as error:
            raise RuntimeToolError(error.reason_code) from error

    def read(self, *, workspace_id: str, session_id: str, private_ref: str) -> bytes:
        try:
            return self._store.read(
                context=_tool_context(workspace_id, session_id),
                locator_prefix="tool-private",
                private_ref=private_ref,
            )
        except RuntimePrivatePayloadError as error:
            raise RuntimeToolError(error.reason_code) from error

    def delete(self, *, workspace_id: str, session_id: str, private_ref: str) -> bool:
        try:
            return self._store.delete(
                context=_tool_context(workspace_id, session_id),
                locator_prefix="tool-private",
                private_ref=private_ref,
            )
        except RuntimePrivatePayloadError as error:
            raise RuntimeToolError(error.reason_code) from error


def canonical_tool_arguments(arguments: dict[str, object]) -> bytes:
    """Return the sole normative serialization used for digest and execution."""
    try:
        payload = json.dumps(
            arguments,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RuntimeToolError("tool_arguments_invalid") from error
    if not payload or len(payload) > MAX_TOOL_PRIVATE_PAYLOAD_BYTES:
        raise RuntimeToolError("tool_arguments_invalid")
    return payload


def tool_arguments_digest(*, digest_key: bytes, canonical_arguments: bytes) -> str:
    """Calculate a domain-separated HMAC safe to expose for confirmation."""
    if len(digest_key) < 32:
        raise RuntimeToolError("tool_digest_key_invalid")
    return hmac.new(digest_key, _DIGEST_DOMAIN + canonical_arguments, hashlib.sha256).hexdigest()


def tool_arguments_summary(arguments: dict[str, object], *, serialized_bytes: int) -> dict[str, object]:
    """Summarize argument shape without persisting keys or values."""
    counts: dict[str, int] = {}
    for value in arguments.values():
        kind = _json_kind(value)
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "root_type": "object",
        "field_count": len(arguments),
        "value_type_counts": {key: counts[key] for key in sorted(counts)},
        "serialized_bytes": serialized_bytes,
    }


def decode_tool_arguments(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeToolError("tool_private_payload_invalid") from error
    if not isinstance(value, dict):
        raise RuntimeToolError("tool_private_payload_invalid")
    return value


def _json_kind(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "invalid"


def _tool_context(workspace_id: str, session_id: str) -> RuntimePrivatePayloadContext:
    return RuntimePrivatePayloadContext(
        namespace="tool-payloads",
        workspace_id=workspace_id,
        session_id=session_id,
        binding_fields=(("payload_schema", "tool-private-v1"),),
    )
