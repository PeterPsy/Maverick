"""Verify Google OpenID ID tokens against Google's signed RSA key set."""

import base64
import json
from threading import Lock
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from core.connected_accounts.google import AccountError, json_request

_keys_lock = Lock()
_keys = {}
_keys_until = 0.0


def decode_base64(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_identity(token, *, client_id, nonce, now=None, keys=None):
    timestamp = time.time() if now is None else now
    try:
        if not isinstance(token, str) or len(token) > 20000:
            raise ValueError()
        header_text, claims_text, signature = token.split(".")
        header = json.loads(decode_base64(header_text))
        claims = json.loads(decode_base64(claims_text))
        if header.get("alg") != "RS256":
            raise ValueError()
        key = (keys if keys is not None else _google_keys(header.get("kid"))).get(header.get("kid"))
        if key is None:
            raise ValueError()
        public_key = rsa.RSAPublicNumbers(int.from_bytes(decode_base64(key["e"]), "big"), int.from_bytes(decode_base64(key["n"]), "big")).public_key()
        public_key.verify(decode_base64(signature), f"{header_text}.{claims_text}".encode(), padding.PKCS1v15(), hashes.SHA256())
        if (claims.get("iss") not in {"https://accounts.google.com", "accounts.google.com"}
                or claims.get("aud") != client_id or claims.get("azp", client_id) != client_id
                or claims.get("nonce") != nonce or claims.get("email_verified") is not True
                or not isinstance(claims.get("sub"), str) or not claims["sub"] or len(claims["sub"]) > 255
                or not isinstance(claims.get("email"), str) or not claims["email"]
                or float(claims["exp"]) <= timestamp or float(claims["iat"]) > timestamp + 60):
            raise ValueError()
        return claims
    except (ValueError, TypeError, KeyError, AttributeError, InvalidSignature):
        raise AccountError("google_identity_invalid", status=401) from None


def _google_keys(kid):
    global _keys, _keys_until
    with _keys_lock:
        if _keys_until <= time.monotonic() or kid not in _keys:
            payload = json_request("https://www.googleapis.com/oauth2/v3/certs")
            _keys = {item["kid"]: item for item in payload.get("keys", []) if item.get("kty") == "RSA"}
            _keys_until = time.monotonic() + 300
        return _keys
