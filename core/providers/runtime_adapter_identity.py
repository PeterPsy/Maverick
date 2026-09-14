"""Stable identity for a registered runtime adapter."""

from __future__ import annotations

import hashlib
import json

from core.providers.errors import AgenticRuntimeError


def runtime_adapter_identity_digest(adapter: object) -> str:
    """Hash declared adapter identity, not mutable source bytes or evidence."""
    provider_definition = None
    describe = getattr(adapter, "provider_definition", None)
    if callable(describe):
        provider_definition = describe()
    concrete = (
        getattr(adapter, "legacy_adapter", None)
        or getattr(adapter, "engine_adapter", None)
        or adapter
    )
    payload = {
        "runtime_engine_id": str(
            getattr(adapter, "runtime_engine_id", "")
            or getattr(provider_definition, "provider_id", "")
        ),
        "adapter_id": str(getattr(adapter, "adapter_id", "")),
        "adapter_version": str(getattr(adapter, "adapter_version", "")),
        "implementation": (
            f"{type(concrete).__module__}.{type(concrete).__qualname__}"
        ),
    }
    if not all(payload.values()):
        raise AgenticRuntimeError("adapter_identity_unavailable")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = ["runtime_adapter_identity_digest"]
