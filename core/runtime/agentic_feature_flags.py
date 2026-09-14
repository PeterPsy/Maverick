"""Operational kill switches for the agentic multimodel rollout."""

from __future__ import annotations

import os
from collections.abc import Mapping


MAVERICK_FEATURE_AGENTIC_PROFILES = "MAVERICK_FEATURE_AGENTIC_PROFILES"
MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT = "MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT"
MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME = "MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME"
MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION = "MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION"
MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE = "MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE"
MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT = "MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT"
MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW = "MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW"
MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW = "MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW"
MAVERICK_FEATURE_ANTIGRAVITY_AGENTIC_PREVIEW = "MAVERICK_FEATURE_ANTIGRAVITY_AGENTIC_PREVIEW"

_DISABLED_VALUES = frozenset({"0", "false", "no", "off"})
_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})
_DEFAULTS = {
    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME: False,
    MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW: False,
    MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW: False,
    MAVERICK_FEATURE_ANTIGRAVITY_AGENTIC_PREVIEW: False,
}


def feature_enabled(
    name: str,
    *,
    default: bool | None = None,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Resolve a strict boolean flag; any malformed configured value disables it."""
    source = os.environ if environment is None else environment
    raw = source.get(name)
    if raw is None or not str(raw).strip():
        return _DEFAULTS.get(name, True) if default is None else default
    normalized = str(raw).strip().lower()
    if normalized in _ENABLED_VALUES:
        return True
    if normalized in _DISABLED_VALUES:
        return False
    return False


def require_agentic_feature(name: str, reason_code: str) -> None:
    """Fail closed at an authoritative runtime boundary when a switch is off."""
    if not feature_enabled(name):
        from core.runtime.hosted_agentic_models import HostedAgenticLoopError

        raise HostedAgenticLoopError(reason_code)


def provider_preview_feature(model_provider_id: str) -> tuple[str, str] | None:
    """Return the provider-specific preview switch and stable blocked reason."""
    if model_provider_id == "google-ai-studio":
        return MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW, "google_agentic_preview_disabled"
    if model_provider_id == "openrouter":
        return MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW, "openrouter_agentic_preview_disabled"
    return None
