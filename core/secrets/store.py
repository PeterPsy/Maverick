"""Store contracts and document adapters for secret-domain records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
import hashlib
import hmac
import secrets
from typing import Any, Callable, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.secrets.errors import SecretBindingError, SecretNotFoundError
from core.secrets.key_material import load_secret_store_key, load_secret_store_keyring, secret_store_key_id
from core.secrets.models import SecretBindingRecord, SecretGrantRecord, SecretRecord


SECRET_VALUE_FORMAT = "mvr3secret2-aesgcm"
LEGACY_SECRET_VALUE_FORMAT = "mvr3secret1"


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

    def save_secret_grant(self, record: SecretGrantRecord) -> SecretGrantRecord:
        ...

    def get_secret_grant(self, grant_id: str) -> SecretGrantRecord:
        ...

    def list_secret_grants(
        self,
        *,
        workspace_id: str | None = None,
        app_id: str | None = None,
        status: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> list[SecretGrantRecord]:
        ...


@dataclass(frozen=True)
class SecretCollections:
    """Collection bundle for secret persistence."""

    secrets: DocumentCollection
    values: DocumentCollection
    bindings: DocumentCollection
    grants: DocumentCollection | None = None


class SecretDocumentStore:
    """Persist secret-domain records in document collections."""

    def __init__(
        self,
        collections: SecretCollections,
        *,
        key_loader: Callable[[], bytes] | None = None,
        keyring_loader: Callable[[], dict[str, bytes]] | None = None,
    ) -> None:
        self.collections = collections
        self._key_loader = key_loader or load_secret_store_key
        self._keyring_loader = keyring_loader or (
            (lambda: {secret_store_key_id(self._key_loader()): self._key_loader()})
            if key_loader is not None
            else load_secret_store_keyring
        )

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
        return _secret_record_from_document(document)

    def get_secret_by_alias(self, alias: str) -> SecretRecord:
        document = self.collections.secrets.find_one({"alias": alias})
        if document is None:
            raise SecretNotFoundError(f"Secret alias `{alias}` was not found.")
        return _secret_record_from_document(document)

    def list_secrets(self) -> list[SecretRecord]:
        return [_secret_record_from_document(document) for document in self.collections.secrets.find({})]

    def save_secret_value(self, *, secret_id: str, raw_value: str) -> None:
        encrypted = _encrypt_secret_value(secret_id=secret_id, raw_value=raw_value, key=self._key_loader())
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
            return _decrypt_secret_value(document, secret_id=secret_id, keyring=self._keyring_loader())
        if document.get("value_format") == LEGACY_SECRET_VALUE_FORMAT:
            return _decrypt_legacy_secret_value(document, key=self._key_loader())
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

    def save_secret_grant(self, record: SecretGrantRecord) -> SecretGrantRecord:
        collection = self._grant_collection()
        collection.update_one(
            {"grant_id": record.grant_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_secret_grant(self, grant_id: str) -> SecretGrantRecord:
        collection = self._grant_collection()
        document = collection.find_one({"grant_id": grant_id})
        if document is None:
            raise SecretBindingError(f"Secret grant `{grant_id}` was not found.")
        return _secret_grant_record_from_document(document)

    def list_secret_grants(
        self,
        *,
        workspace_id: str | None = None,
        app_id: str | None = None,
        status: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> list[SecretGrantRecord]:
        if self.collections.grants is None:
            return []
        query: dict[str, Any] = {}
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        if app_id is not None:
            query["app_id"] = app_id
        if status is not None:
            query["status"] = status
        if resource_type is not None:
            query["resource_type"] = resource_type
        if resource_id is not None:
            query["resource_id"] = resource_id
        return [_secret_grant_record_from_document(document) for document in self.collections.grants.find(query)]

    def _grant_collection(self) -> DocumentCollection:
        if self.collections.grants is None:
            raise SecretBindingError("Secret grant storage is not configured.")
        return self.collections.grants


def _secret_record_from_document(document: dict[str, Any]) -> SecretRecord:
    payload = dict(document)
    payload.setdefault("kind", "generic")
    return SecretRecord(**payload)


def _secret_grant_record_from_document(document: dict[str, Any]) -> SecretGrantRecord:
    payload = dict(document)
    payload.setdefault("resource_type", None)
    payload.setdefault("resource_id", None)
    return SecretGrantRecord(**payload)


def _encrypt_secret_value(*, secret_id: str, raw_value: str, key: bytes) -> dict[str, str]:
    nonce = secrets.token_bytes(12)
    plaintext = raw_value.encode("utf-8")
    aead_key = _aead_key(key)
    key_id = secret_store_key_id(key)
    ciphertext = AESGCM(aead_key).encrypt(nonce, plaintext, _value_aad(secret_id=secret_id, key_id=key_id))
    return {
        "value_format": SECRET_VALUE_FORMAT,
        "value_key_id": key_id,
        "value_nonce": _base64_url(nonce),
        "value_ciphertext": _base64_url(ciphertext),
    }


def _decrypt_secret_value(document: dict[str, Any], *, secret_id: str, keyring: dict[str, bytes]) -> str:
    key_id = str(document.get("value_key_id") or "")
    if not key_id:
        raise SecretNotFoundError("Secret value is missing a key id.")
    key = keyring.get(key_id)
    if key is None:
        raise SecretNotFoundError("Secret value key id is not available.")
    nonce = _base64_url_decode(str(document.get("value_nonce") or ""))
    ciphertext = _base64_url_decode(str(document.get("value_ciphertext") or ""))
    try:
        plaintext = AESGCM(_aead_key(key)).decrypt(nonce, ciphertext, _value_aad(secret_id=secret_id, key_id=key_id))
    except Exception as exc:
        raise SecretNotFoundError("Secret value could not be decrypted.") from exc
    return plaintext.decode("utf-8")


def _aead_key(key: bytes) -> bytes:
    return hashlib.sha256(key).digest()


def _value_aad(*, secret_id: str, key_id: str) -> bytes:
    return f"{SECRET_VALUE_FORMAT}|{secret_id}|{key_id}".encode("utf-8")


def _decrypt_legacy_secret_value(document: dict[str, Any], *, key: bytes) -> str:
    nonce = _base64_url_decode(str(document.get("value_nonce") or ""))
    ciphertext = _base64_url_decode(str(document.get("value_ciphertext") or ""))
    expected_tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    tag = _base64_url_decode(str(document.get("value_tag") or ""))
    if not hmac.compare_digest(tag, expected_tag):
        raise SecretNotFoundError("Secret value could not be decrypted.")
    keystream = _legacy_keystream(key=key, nonce=nonce, length=len(ciphertext))
    plaintext = bytes(left ^ right for left, right in zip(ciphertext, keystream))
    return plaintext.decode("utf-8")


def _legacy_keystream(*, key: bytes, nonce: bytes, length: int) -> bytes:
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
