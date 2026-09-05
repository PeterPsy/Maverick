import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from core.local_runtime.provisioning import INFO, VERSION, seal_auth, write_private_new


class MacAuthProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.private = X25519PrivateKey.generate()
        public = self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.request = {"version": VERSION, "public_key": base64.b64encode(public).decode(),
                        "nonce": base64.b64encode(b"n" * 32).decode(), "device_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                        "origin": "https://maverick.example", "workspace": "default", "expires_at": 1500}
        self.options = dict(origin=self.request["origin"], workspace="default", fingerprint=hashlib.sha256(public).hexdigest(), now=1000)
        self.auth = {"auth_mode": "chatgpt", "tokens": {k: "fake-" + k for k in ("access_token", "refresh_token", "id_token", "account_id")}}

    def seal(self):
        return json.loads(seal_auth(json.dumps(self.request).encode(), json.dumps(self.auth).encode(), **self.options))

    def test_roundtrip_and_no_plaintext(self):
        envelope = self.seal()
        self.assertNotIn("fake-", json.dumps(envelope))
        peer = X25519PublicKey.from_public_bytes(base64.b64decode(envelope["ephemeral_key"]))
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"n" * 32, info=INFO).derive(self.private.exchange(peer))
        sealed = base64.b64decode(envelope["sealed"])
        result = AESGCM(key).decrypt(sealed[:12], sealed[12:], base64.b64decode(envelope["request"]))
        self.assertEqual(json.loads(result)["tokens"], self.auth["tokens"])
        with self.assertRaises(InvalidTag):
            AESGCM(key).decrypt(sealed[:12], sealed[12:], b"different-scope")

    def test_scope_expiry_and_fingerprint_fail_closed(self):
        for field, value in (("origin", "https://evil.example"), ("workspace", "other"), ("expires_at", 1000), ("expires_at", 1901), ("public_key", "bad")):
            original = self.request[field]
            self.request[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): self.seal()
            self.request[field] = original
        self.options["fingerprint"] = "0" * 64
        with self.assertRaises(ValueError): self.seal()

    def test_incomplete_or_non_chatgpt_auth_is_denied(self):
        self.auth["tokens"].pop("refresh_token")
        with self.assertRaises(ValueError): self.seal()
        self.auth = {"auth_mode": "apikey", "OPENAI_API_KEY": "fake-secret"}
        with self.assertRaises(ValueError): self.seal()

    def test_private_exclusive_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "envelope"
            write_private_new(path, b"encrypted")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError): write_private_new(path, b"replacement")
            link = Path(tmp) / "link"
            link.symlink_to(path)
            with self.assertRaises(FileExistsError): write_private_new(link, b"replacement")


if __name__ == "__main__": unittest.main()
