"""Fail-closed release gates and fresh workspace authority at runtime boundaries."""

from __future__ import annotations

from collections.abc import Mapping

from core.providers.errors import AgenticProfileError
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW,
    MAVERICK_FEATURE_GEMINI_CLI_PREVIEW,
    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
    MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW,
    feature_enabled,
)

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
# Native connection certification is independent of Google API certification.
NATIVE_AGENTIC_ATTESTATION_AVAILABLE = False


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
    """Return the authoritative Phase-0 block reason, including unknown providers."""
    from core.runtime.authorization_domain import require_production_authorization
    from core.providers.errors import CapabilityCertificateError

    try:
        require_production_authorization(binding_or_definition)
    except CapabilityCertificateError as error:
        return error.reason_code
    if not is_remote_agentic_identity(binding_or_definition):
        return None
    native = (
        getattr(binding_or_definition, "execution_family", "") == "native_agent"
        and getattr(binding_or_definition, "runtime_engine_id", "") == "gemini-cli"
        and getattr(binding_or_definition, "adapter_id", "") == "gemini-cli-acp"
        and getattr(binding_or_definition, "model_provider_id", "") == "google"
        and getattr(binding_or_definition, "provider_protocol", "") == "acp-ndjson"
        and getattr(binding_or_definition, "provider_api_version", "") == "1"
    )
    if native:
        if not feature_enabled(MAVERICK_FEATURE_GEMINI_CLI_PREVIEW, environment=environment):
            return "gemini_cli_preview_disabled"
        if not NATIVE_AGENTIC_ATTESTATION_AVAILABLE:
            return "native_agentic_attestation_unavailable"
    elif not feature_enabled(
        MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
        environment=environment,
    ):
        return "hosted_agent_runtime_disabled"
    if not native:
        provider_id = str(getattr(binding_or_definition, "model_provider_id", ""))
        provider_flag = REMOTE_AGENTIC_PROVIDER_FLAGS.get(provider_id)
        if provider_flag is None:
            return "remote_agentic_provider_unapproved"
        if not feature_enabled(provider_flag[0], environment=environment):
            return provider_flag[1]
        if not REMOTE_AGENTIC_ATTESTATION_AVAILABLE:
            return "remote_agentic_attestation_unavailable"
    # Resolve at EVERY boundary. A previously accepted snapshot is not a lease
    # and must never mask revocation, store failure, or a workspace change.
    if workspace_store is not None:
        try:
            workspace_attestation = workspace_store.get_data_attestation(workspace_id)
        except Exception:
            workspace_attestation = None
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


def require_remote_agentic_session_admission(
    binding_or_definition: object | None,
    *,
    declared_remote_data_class: object | None = None,
    workspace_id: str | None = None,
    workspace_attestation: WorkspaceDataAttestation | None = None,
    workspace_store: object | None = None,
) -> None:
    """Reject remote sessions before persistence; client declarations never authorize them."""
    from core.runtime.authorization_domain import require_production_authorization
    from core.providers.errors import CapabilityCertificateError

    try:
        require_production_authorization(binding_or_definition)
    except CapabilityCertificateError as error:
        raise AgenticProfileError(error.reason_code) from error
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
    binding: object | None, *, workspace_store: object | None = None, lab_authorization=None,
) -> None:
    """Reject contained or unknown pinned runtimes before provider dispatch."""
    if lab_authorization is not None:
        from core.certification_lab.authority import LabRuntimeAuthorization
        from core.certification_lab.errors import LabAuthorizationError
        from core.runtime.hosted_agentic_models import HostedAgenticLoopError

        if type(lab_authorization) is not LabRuntimeAuthorization or lab_authorization.workspace_store is not workspace_store:
            raise HostedAgenticLoopError("lab_trusted_context_invalid")
        try:
            lab_authorization.validate_binding(binding)
        except LabAuthorizationError as error:
            raise HostedAgenticLoopError(error.reason_code) from error
        return
    reason = remote_agentic_containment_reason(
        binding, workspace_id=getattr(binding, "workspace_id", None),
        workspace_store=workspace_store,
    )
    if reason is None:
        return
    from core.runtime.hosted_agentic_models import HostedAgenticLoopError

    raise HostedAgenticLoopError(reason)


def require_remote_agentic_context(state, context) -> None:
    """Fence a long-lived loop's snapshot against current persisted ownership."""
    from core.runtime.hosted_agentic_models import HostedAgenticLoopError

    session = context.session
    if context.binding != session.execution_binding:
        raise HostedAgenticLoopError("remote_agentic_session_identity_changed")
    if not is_remote_agentic_identity(session.execution_binding):
        return
    try:
        current = state.runtime_store.get_session(session.session_id)
    except Exception as error:
        raise HostedAgenticLoopError("remote_agentic_session_unavailable") from error
    if current.status not in {"created", "running"} or any(
        getattr(current, field) != getattr(session, field)
        for field in ("workspace_id", "execution_binding", "owner_user_id", "created_by_user_id",
                      "agent_type_id", "effective_mode", "runtime_mode")
    ):
        raise HostedAgenticLoopError("remote_agentic_session_identity_changed")
    from core.certification_lab.runtime_context import lab_authorization_for_state
    from core.certification_lab.errors import LabAuthorizationError

    try:
        lab = lab_authorization_for_state(state, current.execution_binding)
        if lab is not None:
            lab.validate_session(current)
    except LabAuthorizationError as error:
        raise HostedAgenticLoopError(error.reason_code) from error
    require_remote_agentic_dispatch(current.execution_binding, workspace_store=state.workspace_store,
                                    lab_authorization=lab)
