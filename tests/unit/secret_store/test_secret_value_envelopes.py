"""Exact clean-install AES-GCM envelopes and predecessor rejection."""

from __future__ import annotations

import base64
import hashlib
import hmac
import unittest

from core.secrets.errors import SecretNotFoundError
from core.secrets.service import create_platform_secret
from core.secrets.store import SecretCollections, SecretDocumentStore
from core.secrets.store import SECRET_VALUE_FORMAT
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from tests.support.collections import FakeCollection


class SecretValueEnvelopeTestCase(unittest.TestCase):
    """Verify authenticated keyring recovery and fail-closed envelope identity."""

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

    def test_secret_store_rejects_valid_predecessor_hmac_xor_values(self) -> None:
        collections = self.make_collections()
        store = SecretDocumentStore(collections, key_loader=lambda: b"legacy-key")
        collections.values.update_one(
            {"secret_id": "sec-legacy"},
            {"$set": {"secret_id": "sec-legacy", **_legacy_value_document(raw_value="legacy-secret", key=b"legacy-key")}},
            upsert=True,
        )

        with self.assertRaises(SecretNotFoundError):
            store.get_secret_value(secret_id="sec-legacy")

    def test_new_format_round_trip_uses_exact_format_secret_and_key_aad(self) -> None:
        collections = self.make_collections()
        key = b"test-key"
        store = SecretDocumentStore(collections, key_loader=lambda:key)
        for value in ("", "Unicode secret \u00e8\u2603"):
            store.save_secret_value(secret_id="sec-format", raw_value=value)
            document = collections.values.find_one({"secret_id":"sec-format"})
            self.assertEqual(document["value_format"], "loopino.secret-value.v1-aesgcm")
            aad = f"{SECRET_VALUE_FORMAT}|sec-format|{document['value_key_id']}".encode()
            plaintext = AESGCM(hashlib.sha256(key).digest()).decrypt(
                _decode(document["value_nonce"]), _decode(document["value_ciphertext"]), aad)
            self.assertEqual(plaintext.decode(), value)
            self.assertEqual(store.get_secret_value(secret_id="sec-format"), value)

    def test_predecessor_aead_is_rejected_and_metadata_relabel_cannot_decrypt(self) -> None:
        collections = self.make_collections()
        key = b"test-key"; key_id = hashlib.sha256(key).hexdigest()[:16]
        nonce = b"123456789012"
        old_aad = f"mvr3secret2-aesgcm|sec-old|{key_id}".encode()
        ciphertext = AESGCM(hashlib.sha256(key).digest()).encrypt(nonce, b"original", old_aad)
        store = SecretDocumentStore(collections, key_loader=lambda:key)
        for identity in ("mvr3secret2-aesgcm", SECRET_VALUE_FORMAT):
            collections.values.update_one({"secret_id":"sec-old"}, {"$set":{
                "secret_id":"sec-old", "value_format":identity, "value_key_id":key_id,
                "value_nonce":_base64_url(nonce), "value_ciphertext":_base64_url(ciphertext),
                "raw_value":"must not bypass rejection",
            }}, upsert=True)
            with self.subTest(identity=identity), self.assertRaises(SecretNotFoundError):
                store.get_secret_value(secret_id="sec-old")

    def test_clean_runtime_rejects_plaintext_and_unknown_formats(self) -> None:
        collections = self.make_collections()
        store = SecretDocumentStore(collections, key_loader=lambda:b"key")
        for identity in (None, "unknown"):
            collections.values.update_one({"secret_id":"sec-invalid"}, {"$set":{
                "secret_id":"sec-invalid", "value_format":identity, "raw_value":"plaintext",
            }}, upsert=True)
            with self.subTest(identity=identity), self.assertRaises(SecretNotFoundError):
                store.get_secret_value(secret_id="sec-invalid")

    def test_missing_key_and_ciphertext_tamper_fail_closed(self) -> None:
        collections = self.make_collections()
        writer = SecretDocumentStore(collections, key_loader=lambda:b"key")
        writer.save_secret_value(secret_id="sec-tamper",raw_value="secret")
        reader = SecretDocumentStore(collections, key_loader=lambda:b"other", keyring_loader=lambda:{})
        with self.assertRaisesRegex(SecretNotFoundError,"key id"):
            reader.get_secret_value(secret_id="sec-tamper")
        document = collections.values.find_one({"secret_id":"sec-tamper"})
        ciphertext = bytearray(_decode(document["value_ciphertext"])); ciphertext[0] ^= 1
        collections.values.update_one({"secret_id":"sec-tamper"}, {"$set":{"value_ciphertext":_base64_url(bytes(ciphertext))}})
        with self.assertRaisesRegex(SecretNotFoundError,"decrypted"):
            writer.get_secret_value(secret_id="sec-tamper")
        collections.values.update_one({"secret_id":"sec-tamper"}, {"$set":{"value_nonce":"not-valid-base64"}})
        with self.assertRaisesRegex(SecretNotFoundError,"decrypted"):
            writer.get_secret_value(secret_id="sec-tamper")


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


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
