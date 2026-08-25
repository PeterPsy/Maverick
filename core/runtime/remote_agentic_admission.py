"""Fail-closed Phase-0 admission for remote agentic runtimes."""

from __future__ import annotations

from collections.abc import Mapping

from core.providers.errors import AgenticProfileError
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW,
    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
    MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW,
    feature_enabled,
)


REMOTE_AGENTIC_PROVIDER_FLAGS = {
    "google-ai-studio": (
        MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW,
        "google_agentic_preview_disabled",
    ),
    "openrouter": (
        MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW,
        "openrouter_agentic_preview_disabled",
    ),
}

# Phase 1 will replace this hard containment barrier with a revision-bound,
# server-verifiable attestation. It is intentionally not environment- or
# client-configurable in Phase 0.
REMOTE_AGENTIC_ATTESTATION_AVAILABLE = False


def is_remote_agentic_identity(binding_or_definition: object | None) -> bool:
    """Treat only the exact local Codex protocol as non-remote."""
    if binding_or_definition is None:
        return False
    return not (
        str(getattr(binding_or_definition, "runtime_engine_id", "")) == "codex"
        and str(getattr(binding_or_definition, "model_provider_id", "")) == "codex"
        and str(getattr(binding_or_definition, "provider_protocol", ""))
        == "codex-app-server-stdio"
    )


def remote_agentic_containment_reason(
    binding_or_definition: object | None,
    *,
    environment: Mapping[str, str] | None = None,
) -> str | None:
    """Return the authoritative Phase-0 block reason, including unknown providers."""
    if not is_remote_agentic_identity(binding_or_definition):
        return None
    if not feature_enabled(
        MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
        environment=environment,
    ):
        return "hosted_agent_runtime_disabled"
    provider_id = str(getattr(binding_or_definition, "model_provider_id", ""))
    provider_flag = REMOTE_AGENTIC_PROVIDER_FLAGS.get(provider_id)
    if provider_flag is None:
        return "remote_agentic_provider_unapproved"
    if not feature_enabled(provider_flag[0], environment=environment):
        return provider_flag[1]
    if not REMOTE_AGENTIC_ATTESTATION_AVAILABLE:
        return "remote_agentic_attestation_unavailable"
    return None


def require_remote_agentic_session_admission(
    binding_or_definition: object | None,
    *,
    declared_remote_data_class: object | None = None,
) -> None:
    """Reject remote sessions before persistence; client declarations never authorize them."""
    if not is_remote_agentic_identity(binding_or_definition):
        return
    if declared_remote_data_class is not None:
        raise AgenticProfileError("remote_agentic_attestation_unavailable")
    reason = remote_agentic_containment_reason(binding_or_definition)
    if reason is not None:
        raise AgenticProfileError(reason)


def require_remote_agentic_dispatch(binding: object | None) -> None:
    """Reject contained or unknown pinned runtimes before provider dispatch."""
    reason = remote_agentic_containment_reason(binding)
    if reason is None:
        return
    from core.runtime.hosted_agentic_models import HostedAgenticLoopError

    raise HostedAgenticLoopError(reason)
