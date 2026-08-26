"""Fail-closed Phase-0 admission for remote agentic runtimes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from core.providers.errors import AgenticProfileError
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW,
    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
    MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW,
    feature_enabled,
)

if TYPE_CHECKING:
    from core.workspaces.data_governance import WorkspaceDataAttestation


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

# Phase 1 supplies revision-bound server attestation records, but later release
# gates must explicitly make the boundary available. It remains intentionally
# non-environment- and non-client-configurable for the P1 closure.
REMOTE_AGENTIC_ATTESTATION_AVAILABLE = False


def is_remote_agentic_identity(binding_or_definition: object | None) -> bool:
    """Treat only the exact local Codex protocol as non-remote."""
    if binding_or_definition is None:
        return False
    return not (
        str(getattr(binding_or_definition, "runtime_engine_id", "")) == "codex"
        and str(getattr(binding_or_definition, "adapter_id", ""))
        == "codex-app-server"
        and str(getattr(binding_or_definition, "model_provider_id", "")) == "codex"
        and str(getattr(binding_or_definition, "provider_protocol", ""))
        == "codex-app-server-stdio"
    )


def remote_agentic_containment_reason(
    binding_or_definition: object | None,
    *,
    environment: Mapping[str, str] | None = None,
    workspace_id: str | None = None,
    workspace_attestation: WorkspaceDataAttestation | None = None,
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
    if workspace_attestation is None:
        return "remote_agentic_attestation_required"
    if workspace_attestation.status == "revoked" and workspace_attestation.well_formed:
        return "remote_agentic_attestation_revoked"
    if not workspace_attestation.authoritative:
        return "remote_agentic_attestation_invalid"
    if not workspace_id or workspace_attestation.workspace_id != workspace_id:
        return "remote_agentic_attestation_workspace_mismatch"
    return None


def require_remote_agentic_session_admission(
    binding_or_definition: object | None,
    *,
    declared_remote_data_class: object | None = None,
    workspace_id: str | None = None,
    workspace_attestation: WorkspaceDataAttestation | None = None,
    workspace_store: object | None = None,
) -> None:
    """Reject remote sessions before persistence; client declarations never authorize them."""
    if declared_remote_data_class is not None:
        raise AgenticProfileError("remote_data_declaration_not_accepted")
    if not is_remote_agentic_identity(binding_or_definition):
        return
    if (
        workspace_attestation is None
        and REMOTE_AGENTIC_ATTESTATION_AVAILABLE
        and workspace_store is not None
    ):
        resolver = getattr(workspace_store, "get_data_attestation", None)
        if callable(resolver) and workspace_id:
            try:
                workspace_attestation = resolver(workspace_id)
            except Exception:
                workspace_attestation = None
    reason = remote_agentic_containment_reason(
        binding_or_definition,
        workspace_id=workspace_id,
        workspace_attestation=workspace_attestation,
    )
    if reason is not None:
        raise AgenticProfileError(reason)


def require_remote_agentic_dispatch(binding: object | None) -> None:
    """Reject contained or unknown pinned runtimes before provider dispatch."""
    reason = remote_agentic_containment_reason(binding)
    if reason is None:
        return
    from core.runtime.hosted_agentic_models import HostedAgenticLoopError

    raise HostedAgenticLoopError(reason)
