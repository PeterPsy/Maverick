"""Google identity signature and claim validation."""
import base64
import json
import unittest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from core.connected_accounts.google import AccountError
from core.connected_accounts.google_identity import verify_identity

class GoogleIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        numbers = cls.key.public_key().public_numbers()
        encode_int = lambda value: base64.urlsafe_b64encode(value.to_bytes((value.bit_length()+7)//8, "big")).decode().rstrip("=")
        cls.keys = {"key": {"e": encode_int(numbers.e), "n": encode_int(numbers.n)}}

    def token(self, changes=None):
        claims = {"iss": "https://accounts.google.com", "aud": "client", "sub": "google-sub", "email": "user@example.com",
                  "email_verified": True, "nonce": "browser-nonce", "exp": 2000, "iat": 900, **(changes or {})}
        encode = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
        signed = encode({"alg": "RS256", "kid": "key"}) + "." + encode(claims)
        signature = self.key.sign(signed.encode(), padding.PKCS1v15(), hashes.SHA256())
        return signed + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")

    def test_signed_identity_checks_audience_nonce_expiry_verified_email(self):
        self.assertEqual(verify_identity(self.token(), client_id="client", nonce="browser-nonce", now=1000, keys=self.keys)["sub"], "google-sub")
        for change in [{"aud": "other"}, {"nonce": "wrong"}, {"exp": 999}, {"email_verified": False}, {"iss": "https://evil.example"}]:
            with self.assertRaisesRegex(AccountError, "google_identity_invalid"):
                verify_identity(self.token(change), client_id="client", nonce="browser-nonce", now=1000, keys=self.keys)

    def test_tampered_signature_is_rejected(self):
        token = self.token()
        parts = token.split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        with self.assertRaisesRegex(AccountError, "google_identity_invalid"):
            verify_identity(".".join(parts), client_id="client", nonce="browser-nonce", now=1000, keys=self.keys)
