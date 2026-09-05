"""Encrypt a Codex auth cache for one independently verified native request.

No network or hosted credential-export surface. Callers own operator approval.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION = "maverick.mac-auth.v1"
INFO = b"maverick.mac-auth.v1"
MAX_BYTES = 65536


def decode_base64(value: object, size: int) -> bytes:
    if not isinstance(value, str):
        raise ValueError("Invalid provisioning request.")
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError as error:
        raise ValueError("Invalid provisioning request.") from error
    if len(decoded) != size:
        raise ValueError("Invalid provisioning request.")
    return decoded


def validate_request(raw: bytes, *, origin: str, workspace: str, fingerprint: str, now: int) -> dict:
    if len(raw) > 4096:
        raise ValueError("Provisioning request too large.")
    request = json.loads(raw)
    keys = {"version", "public_key", "nonce", "device_id", "origin", "workspace", "expires_at"}
    if not isinstance(request, dict) or set(request) != keys or request["version"] != VERSION:
        raise ValueError("Invalid provisioning request.")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("An exact HTTPS origin is required.")
    if request["origin"] != origin or request["workspace"] != workspace:
        raise ValueError("Provisioning scope mismatch.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", workspace):
        raise ValueError("Invalid workspace.")
    if not isinstance(request["device_id"], str) or not re.fullmatch(r"[A-Fa-f0-9-]{36}", request["device_id"]):
        raise ValueError("Invalid device identity.")
    expiry = request["expires_at"]
    if type(expiry) is not int or not now < expiry <= now + 900:
        raise ValueError("Provisioning request expired or outside allowed lifetime.")
    key = decode_base64(request["public_key"], 32)
    decode_base64(request["nonce"], 32)
    expected = hashlib.sha256(key).hexdigest()
    if fingerprint.lower() != expected:
        raise ValueError("Device fingerprint mismatch.")
    return request


def validated_auth(raw: bytes) -> bytes:
    if len(raw) > MAX_BYTES:
        raise ValueError("Auth cache too large.")
    auth = json.loads(raw)
    if not isinstance(auth, dict) or auth.get("auth_mode") != "chatgpt" or auth.get("OPENAI_API_KEY"):
        raise ValueError("Only a managed ChatGPT auth cache is supported.")
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict) or any(not isinstance(tokens.get(k), str) or not tokens[k] for k in ("access_token", "refresh_token", "id_token", "account_id")):
        raise ValueError("Incomplete ChatGPT auth cache.")
    # Do not copy unrelated configuration, provider overrides or arbitrary fields.
    result = {"auth_mode": "chatgpt", "OPENAI_API_KEY": None,
              "tokens": {k: tokens[k] for k in ("access_token", "refresh_token", "id_token", "account_id")}}
    if isinstance(auth.get("last_refresh"), str):
        result["last_refresh"] = auth["last_refresh"]
    return json.dumps(result, separators=(",", ":")).encode()


def seal_auth(request_raw: bytes, auth_raw: bytes, *, origin: str, workspace: str, fingerprint: str, now: int | None = None) -> bytes:
    request = validate_request(request_raw, origin=origin, workspace=workspace, fingerprint=fingerprint, now=int(time.time()) if now is None else now)
    auth = validated_auth(auth_raw)
    private = X25519PrivateKey.generate()
    peer = X25519PublicKey.from_public_bytes(decode_base64(request["public_key"], 32))
    shared = private.exchange(peer)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=decode_base64(request["nonce"], 32), info=INFO).derive(shared)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, auth, request_raw)
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    encode = lambda data: base64.b64encode(data).decode("ascii")
    return json.dumps({"version": VERSION, "request": encode(request_raw), "ephemeral_key": encode(public), "sealed": encode(nonce + ciphertext)}, separators=(",", ":")).encode()


def write_private_new(path: Path, data: bytes) -> None:
    """Never follow a symlink or overwrite an existing artifact."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(data)
