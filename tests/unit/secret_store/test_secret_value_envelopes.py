"""Tests for Core Secrets value envelope compatibility."""

from __future__ import annotations

import base64
import hashlib
import hmac
import unittest

from core.secrets.errors import SecretNotFoundError
from core.secrets.service import create_platform_secret
from core.secrets.store import SecretCollections, SecretDocumentStore
from tests.support.collections import FakeCollection


class SecretValueEnvelopeTestCase(unittest.TestCase):
    """Verify encrypted value envelope keying and legacy read behavior."""

    def make_collections(self) -> SecretCollections:
        return SecretCollections(
            secrets=FakeCollection(),
            values=FakeCollection(),
            bindings=FakeCollection(),
            grants=FakeCollection(),
        )

    def test_secret_store_decrypts_with_key_id_from_keyring(self) -> None:
        collections = self.make_collections()
        writer = SecretDocumentStore(collections, key_loader=lambda: b"old-key")
        record = create_platform_secret(writer, label="Rotated Key", raw_value="rotatable-secret", alias="rotatable-key")
        reader = SecretDocumentStore(
            collections,
            key_loader=lambda: b"new-key",
            keyring_loader=lambda: {
                hashlib.sha256(b"old-key").hexdigest()[:16]: b"old-key",
                hashlib.sha256(b"new-key").hexdigest()[:16]: b"new-key",
            },
        )

        self.assertEqual(reader.get_secret_value(secret_id=record.secret_id), "rotatable-secret")

    def test_secret_store_aad_binds_ciphertext_to_secret_id(self) -> None:
        collections = self.make_collections()
        store = SecretDocumentStore(collections, key_loader=lambda: b"test-key")
        record = create_platform_secret(store, label="Bound Secret", raw_value="bound-secret", alias="bound-secret")
        stored_value = collections.values.find_one({"secret_id": record.secret_id})
        assert stored_value is not None
        copied_value = {**stored_value, "secret_id": "sec-copied"}
        collections.values.update_one({"secret_id": "sec-copied"}, {"$set": copied_value}, upsert=True)

        with self.assertRaises(SecretNotFoundError):
            store.get_secret_value(secret_id="sec-copied")

    def test_secret_store_can_read_legacy_hmac_xor_values(self) -> None:
        collections = self.make_collections()
        store = SecretDocumentStore(collections, key_loader=lambda: b"legacy-key")
        collections.values.update_one(
            {"secret_id": "sec-legacy"},
            {"$set": {"secret_id": "sec-legacy", **_legacy_value_document(raw_value="legacy-secret", key=b"legacy-key")}},
            upsert=True,
        )

        self.assertEqual(store.get_secret_value(secret_id="sec-legacy"), "legacy-secret")


def _legacy_value_document(*, raw_value: str, key: bytes) -> dict[str, str]:
    nonce = b"legacy-test-nonce"
    plaintext = raw_value.encode("utf-8")
    keystream = _legacy_keystream(key=key, nonce=nonce, length=len(plaintext))
    ciphertext = bytes(left ^ right for left, right in zip(plaintext, keystream))
    tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    return {
        "value_format": "mvr3secret1",
        "value_nonce": _base64_url(nonce),
        "value_ciphertext": _base64_url(ciphertext),
        "value_tag": _base64_url(tag),
    }


def _legacy_keystream(*, key: bytes, nonce: bytes, length: int) -> bytes:
    chunks: list[bytes] = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < length:
        chunks.append(hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(chunks)[:length]


def _base64_url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
