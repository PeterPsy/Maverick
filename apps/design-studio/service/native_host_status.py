"""Validate the launcher-owned, redaction-safe native host handshake."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import time
from typing import Any

from official_oci_validation import reject_duplicate_pairs


HOST_STATUS_FILE = "native-host-status.json"
MAX_HOST_STATUS_BYTES = 64 * 1024
MODEL_STATES = {"ready", "degraded", "disabled"}


def read_live_model_bridge(
    app_data_root: Path,
    *,
    manifest_digest: str,
    unavailable_reason: str,
    wait_seconds: float = 0.0,
) -> dict[str, Any]:
    """Read a matching ready handshake through bounded in-place rewrite races."""
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        payload = _read_host_status(Path(app_data_root) / HOST_STATUS_FILE)
        model = model_bridge_from_status(
            payload,
            manifest_digest=manifest_digest,
        )
        if model is not None:
            return model
        remaining = deadline - time.monotonic()
        waitable = not payload or _is_matching_startup(
            payload,
            manifest_digest=manifest_digest,
        )
        if remaining <= 0 or not waitable:
            break
        time.sleep(min(0.05, remaining))
    return {
        "state": "degraded",
        "reason": unavailable_reason,
        "semantic_enrichment": False,
    }


def model_bridge_from_status(
    payload: object,
    *,
    manifest_digest: str,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    model = payload.get("model_bridge")
    if (
        payload.get("schema_version") != "1"
        or payload.get("mode") != "official-native"
        or payload.get("state") != "ready"
        or payload.get("manifest_digest") != manifest_digest
        or not isinstance(model, dict)
        or model.get("state") not in MODEL_STATES
        or model.get("semantic_enrichment") is not False
    ):
        return None
    return dict(model)


def _read_host_status(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return {}
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or metadata.st_size > MAX_HOST_STATUS_BYTES
        ):
            return {}
        chunks: list[bytes] = []
        remaining = MAX_HOST_STATUS_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        body = b"".join(chunks)
        if len(body) > MAX_HOST_STATUS_BYTES:
            return {}
        payload = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {}
    finally:
        os.close(descriptor)
    return payload if isinstance(payload, dict) else {}


def _is_matching_startup(payload: object, *, manifest_digest: str) -> bool:
    return bool(
        isinstance(payload, dict)
        and payload.get("schema_version") == "1"
        and payload.get("mode") == "official-native"
        and payload.get("state") == "starting"
        and payload.get("manifest_digest") == manifest_digest
    )


__all__ = ["model_bridge_from_status", "read_live_model_bridge"]
