"""Store contracts and document adapters for secret-domain records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
import hashlib
import hmac
import secrets
from typing import Any, Callable, Protocol

from core.secrets.errors import SecretBindingError, SecretNotFoundError
from core.secrets.key_material import load_secret_store_key
from core.secrets.models import SecretBindingRecord, SecretRecord


SECRET_VALUE_FORMAT = "mvr3secret1"


class DocumentCollection(Protocol):
    """Minimal collection protocol used by document store adapters."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...

    def delete_one(self, query: dict[str, Any]) -> Any:
        ...


class SecretStore(Protocol):
    """Persistence contract for secret metadata, raw values, and bindings."""

    def save_secret(self, record: SecretRecord) -> SecretRecord:
        ...

    def get_secret(self, secret_id: str) -> SecretRecord:
        ...

    def get_secret_by_alias(self, alias: str) -> SecretRecord:
        ...

    def list_secrets(self) -> list[SecretRecord]:
        ...

    def save_secret_value(self, *, secret_id: str, raw_value: str) -> None:
        ...

    def get_secret_value(self, *, secret_id: str) -> str:
        ...

    def delete_secret_value(self, *, secret_id: str) -> None:
        ...

    def save_secret_binding(self, record: SecretBindingRecord) -> SecretBindingRecord:
        ...

    def get_secret_binding(self, binding_id: str) -> SecretBindingRecord:
        ...

    def list_secret_bindings(
        self,
        *,
        workspace_id: str | None = None,
        app_id: str | None = None,
        provider_id: str | None = None,
        scope: str | None = None,
        logical_name: str | None = None,
    ) -> list[SecretBindingRecord]:
        ...


@dataclass(frozen=True)
class SecretCollections:
    """Collection bundle for secret persistence."""

    secrets: DocumentCollection
    values: DocumentCollection
    bindings: DocumentCollection


class SecretDocumentStore:
    """Persist secret-domain records in document collections."""

    def __init__(self, collections: SecretCollections, *, key_loader: Callable[[], bytes] | None = None) -> None:
        self.collections = collections
        self._key_loader = key_loader or load_secret_store_key

    def save_secret(self, record: SecretRecord) -> SecretRecord:
        self.collections.secrets.update_one(
            {"secret_id": record.secret_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_secret(self, secret_id: str) -> SecretRecord:
        document = self.collections.secrets.find_one({"secret_id": secret_id})
        if document is None:
            raise SecretNotFoundError(f"Secret `{secret_id}` was not found.")
        return SecretRecord(**document)

    def get_secret_by_alias(self, alias: str) -> SecretRecord:
        document = self.collections.secrets.find_one({"alias": alias})
        if document is None:
            raise SecretNotFoundError(f"Secret alias `{alias}` was not found.")
        return SecretRecord(**document)

    def list_secrets(self) -> list[SecretRecord]:
        return [SecretRecord(**document) for document in self.collections.secrets.find({})]

    def save_secret_value(self, *, secret_id: str, raw_value: str) -> None:
        encrypted = _encrypt_secret_value(raw_value, key=self._key_loader())
        self.collections.values.update_one(
            {"secret_id": secret_id},
            {"$set": {"secret_id": secret_id, **encrypted}},
            upsert=True,
        )

    def get_secret_value(self, *, secret_id: str) -> str:
        document = self.collections.values.find_one({"secret_id": secret_id})
        if document is None:
            raise SecretNotFoundError(f"Secret value for `{secret_id}` was not found.")
        if document.get("value_format") == SECRET_VALUE_FORMAT:
            return _decrypt_secret_value(document, key=self._key_loader())
        if "raw_value" in document:
            return str(document["raw_value"])
        raise SecretNotFoundError(f"Secret value for `{secret_id}` was not found.")

    def delete_secret_value(self, *, secret_id: str) -> None:
        self.collections.values.delete_one({"secret_id": secret_id})

    def save_secret_binding(self, record: SecretBindingRecord) -> SecretBindingRecord:
        self.collections.bindings.update_one(
            {"binding_id": record.binding_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_secret_binding(self, binding_id: str) -> SecretBindingRecord:
        document = self.collections.bindings.find_one({"binding_id": binding_id})
        if document is None:
            raise SecretBindingError(f"Secret binding `{binding_id}` was not found.")
        return SecretBindingRecord(**document)

    def list_secret_bindings(
        self,
        *,
        workspace_id: str | None = None,
        app_id: str | None = None,
        provider_id: str | None = None,
        scope: str | None = None,
        logical_name: str | None = None,
    ) -> list[SecretBindingRecord]:
        query: dict[str, Any] = {}
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        if app_id is not None:
            query["app_id"] = app_id
        if provider_id is not None:
            query["provider_id"] = provider_id
        if scope is not None:
            query["scope"] = scope
        if logical_name is not None:
            query["logical_name"] = logical_name
        return [SecretBindingRecord(**document) for document in self.collections.bindings.find(query)]


def _encrypt_secret_value(raw_value: str, *, key: bytes) -> dict[str, str]:
    nonce = secrets.token_bytes(16)
    plaintext = raw_value.encode("utf-8")
    keystream = _keystream(key=key, nonce=nonce, length=len(plaintext))
    ciphertext = bytes(left ^ right for left, right in zip(plaintext, keystream))
    tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    return {
        "value_format": SECRET_VALUE_FORMAT,
        "value_nonce": _base64_url(nonce),
        "value_ciphertext": _base64_url(ciphertext),
        "value_tag": _base64_url(tag),
    }


def _decrypt_secret_value(document: dict[str, Any], *, key: bytes) -> str:
    nonce = _base64_url_decode(str(document.get("value_nonce") or ""))
    ciphertext = _base64_url_decode(str(document.get("value_ciphertext") or ""))
    expected_tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    tag = _base64_url_decode(str(document.get("value_tag") or ""))
    if not hmac.compare_digest(tag, expected_tag):
        raise SecretNotFoundError("Secret value could not be decrypted.")
    keystream = _keystream(key=key, nonce=nonce, length=len(ciphertext))
    plaintext = bytes(left ^ right for left, right in zip(ciphertext, keystream))
    return plaintext.decode("utf-8")


def _keystream(*, key: bytes, nonce: bytes, length: int) -> bytes:
    chunks: list[bytes] = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < length:
        chunks.append(hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(chunks)[:length]


def _base64_url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _base64_url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode("ascii"))
