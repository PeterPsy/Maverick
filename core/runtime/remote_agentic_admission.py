"""Fail-closed admission for certified remote agentic runtimes."""

from __future__ import annotations

from collections.abc import Mapping
from core.providers.agentic_data_policies import (
    remote_profile_requires_fake_data_attestation,
)
from core.providers.errors import AgenticProfileError
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_ANTIGRAVITY_AGENTIC_PREVIEW,
    MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW,
    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
    MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW,
    feature_enabled,
)
from core.workspaces.data_governance import WorkspaceDataAttestation


REMOTE_AGENTIC_PROVIDER_FLAGS = {
    "antigravity-cli": (
        MAVERICK_FEATURE_ANTIGRAVITY_AGENTIC_PREVIEW,
        "antigravity_agentic_preview_disabled",
    ),
    "google-ai-studio": (
        MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW,
        "google_agentic_preview_disabled",
    ),
    "openrouter": (
        MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW,
        "openrouter_agentic_preview_disabled",
    ),
}

# The server-owned, revision-bound attestation boundary is part of this
# candidate. Provider flags remain the independent operator kill switches; no
# environment or client input can replace the persisted workspace record.
REMOTE_AGENTIC_ATTESTATION_AVAILABLE = True


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
    workspace_store: object | None = None,
) -> str | None:
    """Return the authoritative block reason, including current workspace state."""
    reason = remote_agentic_availability_reason(
        binding_or_definition,
        environment=environment,
    )
    if reason is not None:
        return reason
    if not is_remote_agentic_identity(binding_or_definition):
        return None
    if not remote_profile_requires_fake_data_attestation(binding_or_definition):
        return None
    if not REMOTE_AGENTIC_ATTESTATION_AVAILABLE:
        return "remote_agentic_attestation_unavailable"
    if workspace_store is not None:
        workspace_attestation = _resolve_workspace_attestation(
            workspace_store,
            workspace_id=workspace_id,
        )
    if workspace_attestation is None:
        return "remote_agentic_attestation_required"
    if not isinstance(workspace_attestation, WorkspaceDataAttestation):
        return "remote_agentic_attestation_invalid"
    if workspace_attestation.status == "revoked" and workspace_attestation.well_formed:
        return "remote_agentic_attestation_revoked"
    if not workspace_attestation.authoritative:
        return "remote_agentic_attestation_invalid"
    if not workspace_id or workspace_attestation.workspace_id != workspace_id:
        return "remote_agentic_attestation_workspace_mismatch"
    return None


def remote_agentic_availability_reason(
    binding_or_definition: object | None,
    *,
    environment: Mapping[str, str] | None = None,
) -> str | None:
    """Return provider/kill-switch availability without inventing workspace authority."""
    if not is_remote_agentic_identity(binding_or_definition):
        return None
    if not feature_enabled(
        MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
        environment=environment,
    ):
        return "hosted_agent_runtime_disabled"
    runtime_engine_id = str(
        getattr(binding_or_definition, "runtime_engine_id", "")
    )
    provider_id = str(getattr(binding_or_definition, "model_provider_id", ""))
    provider_flag = REMOTE_AGENTIC_PROVIDER_FLAGS.get(
        runtime_engine_id,
        REMOTE_AGENTIC_PROVIDER_FLAGS.get(provider_id),
    )
    if provider_flag is None:
        return "remote_agentic_provider_unapproved"
    if not feature_enabled(provider_flag[0], environment=environment):
        return provider_flag[1]
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
    reason = remote_agentic_containment_reason(
        binding_or_definition,
        workspace_id=workspace_id,
        workspace_attestation=workspace_attestation,
        workspace_store=workspace_store,
    )
    if reason is not None:
        raise AgenticProfileError(reason)


def require_remote_agentic_dispatch(
    binding: object | None,
    *,
    workspace_id: str | None = None,
    workspace_attestation: WorkspaceDataAttestation | None = None,
    workspace_store: object | None = None,
) -> None:
    """Reject contained or unknown pinned runtimes before provider dispatch."""
    reason = remote_agentic_containment_reason(
        binding,
        workspace_id=workspace_id,
        workspace_attestation=workspace_attestation,
        workspace_store=workspace_store,
    )
    if reason is None:
        return
    from core.runtime.hosted_agentic_models import HostedAgenticLoopError

    raise HostedAgenticLoopError(reason)


def require_remote_agentic_runtime_availability(binding: object | None) -> None:
    """Fence provider runtime resolution while leaving workspace checks to live boundaries."""
    reason = remote_agentic_availability_reason(binding)
    if reason is None:
        return
    from core.runtime.hosted_agentic_models import HostedAgenticLoopError

    raise HostedAgenticLoopError(reason)


def require_remote_agentic_authority(
    binding: object | None,
    *,
    workspace_id: str | None,
    workspace_store: object | None,
) -> None:
    """Reject stale workspace authority before snapshot resolution or refresh."""
    reason = remote_agentic_containment_reason(
        binding,
        workspace_id=workspace_id,
        workspace_store=workspace_store,
    )
    if reason is None:
        return
    from core.providers.errors import CapabilityCertificateError

    raise CapabilityCertificateError(reason)


def _resolve_workspace_attestation(
    workspace_store: object | None,
    *,
    workspace_id: str | None,
) -> WorkspaceDataAttestation | None:
    if workspace_store is None or not workspace_id:
        return None
    resolver = getattr(workspace_store, "get_data_attestation", None)
    if not callable(resolver):
        return None
    try:
        return resolver(workspace_id)
    except Exception:
        return None
