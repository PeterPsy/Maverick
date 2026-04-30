"""Secret-store encryption key loading."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Mapping


def load_secret_store_key(environment: Mapping[str, str] | None = None) -> bytes:
    """Return the secret-store encryption key bytes for the current process."""
    env = environment if environment is not None else os.environ
    key_file = env.get("MAVERICK_SECRET_KEY_FILE", "").strip()
    if key_file:
        try:
            configured = Path(key_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"MAVERICK_SECRET_KEY_FILE could not be read: {key_file}") from exc
        if not configured:
            raise RuntimeError(f"MAVERICK_SECRET_KEY_FILE is empty: {key_file}")
        return secret_store_key_from_text(configured)

    configured = env.get("MAVERICK_SECRET_STORE_KEY", "").strip()
    if configured:
        return secret_store_key_from_text(configured)
    if env.get("MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS") == "1":
        return secret_store_key_from_text("maverick-local-secret-store")
    raise RuntimeError("MAVERICK_SECRET_KEY_FILE is required.")


def secret_store_key_from_text(value: str) -> bytes:
    """Derive fixed-length encryption key material from one local secret string."""
    return hashlib.sha256(value.encode("utf-8")).digest()
