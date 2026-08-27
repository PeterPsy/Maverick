"""Encrypted, quota-bounded private blob storage under runtime session roots."""

from __future__ import annotations

import base64
from contextlib import contextmanager
import fcntl
import hmac
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.runtime.paths import runtime_session_root
from core.runtime.private_payload_models import (
    PRIVATE_PAYLOAD_ENCRYPTION_PROFILE,
    RuntimePrivatePayloadContext,
    RuntimePrivatePayloadError,
)
from core.secrets.key_material import secret_store_key_id


MAX_PRIVATE_PAYLOAD_BYTES = 2 * 1_048_576
MAX_PRIVATE_PAYLOAD_DOCUMENT_BYTES = 4 * 1_048_576
_TOKEN_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class EncryptedRuntimePrivatePayloadStore:
    """Issue opaque locators and encrypt blobs with context-bound AES-GCM."""

    def __init__(
        self,
        *,
        repository_root: Path,
        key_loader: Callable[[], bytes],
        keyring_loader: Callable[[], dict[str, bytes]] | None = None,
    ) -> None:
        self.repository_root = repository_root
        self._key_loader = key_loader
        self._keyring_loader = keyring_loader

    def put(
        self,
        *,
        context: RuntimePrivatePayloadContext,
        locator_prefix: str,
        payload: bytes,
        max_blob_bytes: int,
        max_session_bytes: int,
        replace_ref: str | None = None,
        private_ref: str | None = None,
        idempotent_ref: bool = False,
    ) -> str:
        if not payload or len(payload) > max_blob_bytes:
            raise RuntimePrivatePayloadError("private_payload_size_invalid")
        key = self._current_key()
        token = uuid4().hex
        private_ref = private_ref or f"{locator_prefix}:v1:{token}"
        path = self._payload_path(context, locator_prefix, private_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _locked_namespace(path.parent):
            if idempotent_ref and path.is_file():
                existing = self.read(
                    context=context,
                    locator_prefix=locator_prefix,
                    private_ref=private_ref,
                )
                if hmac.compare_digest(existing, payload):
                    return private_ref
                raise RuntimePrivatePayloadError(
                    "private_payload_identity_conflict"
                )
            replaced_size = self._stored_size(context, locator_prefix, replace_ref)
            current_size = sum(
                self._document_payload_size(item)
                for item in path.parent.glob("*.json")
                if item.is_file()
            )
            if current_size - replaced_size + len(payload) > max_session_bytes:
                raise RuntimePrivatePayloadError("private_payload_session_quota_exceeded")
            nonce = os.urandom(12)
            ciphertext = AESGCM(key).encrypt(
                nonce,
                payload,
                self._associated_data(context, private_ref),
            )
            document = {
                "schema_version": "1",
                "encryption_profile": PRIVATE_PAYLOAD_ENCRYPTION_PROFILE,
                "key_id": secret_store_key_id(key),
                "size_bytes": len(payload),
                "nonce": _encode(nonce),
                "ciphertext": _encode(ciphertext),
            }
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=path.parent,
                    prefix=f".{path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    json.dump(document, handle, separators=(",", ":"), sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                    temporary_path = Path(handle.name)
                os.replace(temporary_path, path)
            finally:
                if temporary_path is not None and temporary_path.exists():
                    try:
                        temporary_path.unlink(missing_ok=True)
                    except OSError:
                        pass
        return private_ref

    def read(
        self,
        *,
        context: RuntimePrivatePayloadContext,
        locator_prefix: str,
        private_ref: str,
    ) -> bytes:
        path = self._payload_path(context, locator_prefix, private_ref)
        try:
            if path.stat().st_size > MAX_PRIVATE_PAYLOAD_DOCUMENT_BYTES:
                raise ValueError("private payload document too large")
            document = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(document, dict)
                or document.get("schema_version") != "1"
                or document.get("encryption_profile") != PRIVATE_PAYLOAD_ENCRYPTION_PROFILE
            ):
                raise ValueError("private payload metadata invalid")
            key_id = str(document.get("key_id") or "")
            key = self._keyring().get(key_id)
            if key is None:
                raise ValueError("private payload key unavailable")
            size_bytes = document.get("size_bytes")
            if (
                not isinstance(size_bytes, int)
                or isinstance(size_bytes, bool)
                or not 1 <= size_bytes <= MAX_PRIVATE_PAYLOAD_BYTES
            ):
                raise ValueError("private payload size invalid")
            payload = AESGCM(key).decrypt(
                _decode(document.get("nonce")),
                _decode(document.get("ciphertext")),
                self._associated_data(context, private_ref),
            )
            if len(payload) != size_bytes:
                raise ValueError("private payload size mismatch")
            return payload
        except (OSError, ValueError, TypeError) as error:
            raise RuntimePrivatePayloadError("private_payload_unavailable") from error
        except Exception as error:
            raise RuntimePrivatePayloadError("private_payload_integrity_failed") from error

    def delete(
        self,
        *,
        context: RuntimePrivatePayloadContext,
        locator_prefix: str,
        private_ref: str,
    ) -> bool:
        path = self._payload_path(context, locator_prefix, private_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _locked_namespace(path.parent):
            try:
                path.unlink()
            except FileNotFoundError:
                return False
            except OSError as error:
                raise RuntimePrivatePayloadError("private_payload_delete_failed") from error
        return True

    def _payload_path(
        self,
        context: RuntimePrivatePayloadContext,
        locator_prefix: str,
        private_ref: str,
    ) -> Path:
        expected = f"{locator_prefix}:v1:"
        if not private_ref.startswith(expected):
            raise RuntimePrivatePayloadError("private_payload_locator_invalid")
        token = private_ref.removeprefix(expected)
        if not _TOKEN_PATTERN.fullmatch(token):
            raise RuntimePrivatePayloadError("private_payload_locator_invalid")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", context.namespace):
            raise RuntimePrivatePayloadError("private_payload_namespace_invalid")
        root = runtime_session_root(
            workspace_id=context.workspace_id,
            session_id=context.session_id,
            start_path=self.repository_root,
        )
        return root / "private" / context.namespace / f"{token}.json"

    def _stored_size(
        self,
        context: RuntimePrivatePayloadContext,
        locator_prefix: str,
        private_ref: str | None,
    ) -> int:
        if not private_ref:
            return 0
        path = self._payload_path(context, locator_prefix, private_ref)
        return self._document_payload_size(path) if path.is_file() else 0

    @staticmethod
    def _document_payload_size(path: Path) -> int:
        try:
            if path.stat().st_size > MAX_PRIVATE_PAYLOAD_DOCUMENT_BYTES:
                raise ValueError("private payload quota document too large")
            document = json.loads(path.read_text(encoding="utf-8"))
            size_bytes = document.get("size_bytes") if isinstance(document, dict) else None
            if (
                not isinstance(size_bytes, int)
                or isinstance(size_bytes, bool)
                or not 1 <= size_bytes <= MAX_PRIVATE_PAYLOAD_BYTES
            ):
                raise ValueError("private payload quota metadata invalid")
            return size_bytes
        except (OSError, ValueError, TypeError) as error:
            raise RuntimePrivatePayloadError("private_payload_quota_metadata_invalid") from error

    @staticmethod
    def _associated_data(context: RuntimePrivatePayloadContext, private_ref: str) -> bytes:
        payload = {
            "namespace": context.namespace,
            "workspace_id": context.workspace_id,
            "session_id": context.session_id,
            "private_ref": private_ref,
            "binding_fields": list(context.binding_fields),
        }
        return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    def _current_key(self) -> bytes:
        key = self._key_loader()
        if len(key) != 32:
            raise RuntimePrivatePayloadError("private_payload_key_invalid")
        return key

    def _keyring(self) -> dict[str, bytes]:
        if self._keyring_loader is not None:
            return self._keyring_loader()
        key = self._current_key()
        return {secret_store_key_id(key): key}


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("private payload encoding invalid")
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode("ascii"))


@contextmanager
def _locked_namespace(root: Path):
    lock_path = root / ".private-payload.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
