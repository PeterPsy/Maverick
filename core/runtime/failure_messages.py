"""Stable public messages for structured runtime failure codes."""

from __future__ import annotations

import re


_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PUBLIC_MESSAGES = {
    "adapter_artifact_mismatch": (
        "This chat uses an older runtime profile and must be upgraded before it can continue."
    ),
    "adapter_version_mismatch": "The certified runtime adapter version is unavailable.",
    "agent_step_limit_reached": "The runtime reached its step limit before completing the request.",
    "agent_tool_call_limit_reached": "The runtime reached its tool-call limit before completing the request.",
    "agent_cost_estimate_unavailable": (
        "The runtime could not prove that the provider request fits the configured cost budget."
    ),
    "agent_cost_limit_reached": "The runtime reached its configured cost limit.",
    "agent_final_output_empty": (
        "The model completed the request without a usable final answer."
    ),
    "agent_finalization_recovery_exhausted": (
        "The model requested another tool after the single governed finalization recovery."
    ),
    "agent_finalization_catalog_not_empty": (
        "The runtime refused a finalization request whose tool catalog was not closed."
    ),
    "agent_finalization_phase_invalid": (
        "The runtime refused an invalid hosted finalization phase."
    ),
    "agent_finalization_reserve_unavailable": (
        "The runtime could not preserve the resources required for a governed final answer."
    ),
    "agent_finalization_reserve_violation": (
        "The provider request exceeded its reserved finalization allocation."
    ),
    "agent_finalization_time_reserve_reached": (
        "The runtime stopped the request to preserve its finalization deadline."
    ),
    "agent_finalization_tool_call_forbidden": (
        "The model requested a tool after the governed tool catalog was closed."
    ),
    "agent_input_token_limit_reached": "The runtime reached its input-token limit.",
    "agent_output_token_limit_reached": "The runtime reached its output-token limit.",
    "agent_time_limit_reached": "The runtime reached its wall-time limit.",
    "agent_tool_result_limit_reached": "The runtime reached its tool-result limit.",
    "agentic_app_references_not_effective": (
        "The selected runtime profile is not certified for app references."
    ),
    "agentic_app_reference_metadata_invalid": (
        "An app reference has invalid server-verifiable metadata."
    ),
    "agentic_attachment_metadata_invalid": (
        "An attachment lacks the server-verifiable media metadata required by this runtime."
    ),
    "agentic_attachment_modality_not_certified": (
        "The selected runtime profile is not certified for this attachment type."
    ),
    "agentic_cli_not_effective": "CLI access is not effective for this runtime turn.",
    "agentic_confirmation_not_effective": (
        "Confirmation resume is not effective for this runtime turn."
    ),
    "agentic_context_operation_unknown": "The requested runtime operation is unsupported.",
    "agentic_filesystem_read_not_effective": (
        "Filesystem read access is not effective for this runtime turn."
    ),
    "agentic_filesystem_write_not_effective": (
        "Filesystem write access is not effective for this runtime turn."
    ),
    "agentic_mcp_not_effective": "MCP access is not effective for this runtime turn.",
    "agentic_recovery_not_effective": "Recovery is not effective for this runtime turn.",
    "agentic_shell_not_effective": "Shell access is not effective for this runtime turn.",
    "agentic_skill_catalog_not_effective": (
        "The selected runtime profile is not certified for skills."
    ),
    "agentic_session_skill_catalog_immutable": (
        "The runtime session skill catalog is pinned and cannot be replaced by a turn."
    ),
    "agentic_skill_metadata_invalid": (
        "An invoked skill has invalid server-verifiable metadata."
    ),
    "certificate_revoked": "This model profile is no longer authorized.",
    "certificate_expired": "This model profile certificate has expired.",
    "certificate_inactive": "This model profile certificate is not active.",
    "certificate_missing": "This model profile has no capability certificate.",
    "certificate_missing_status": "This model profile certificate has no live status.",
    "certificate_tcb_drift": "The certified execution boundary has changed.",
    "credential_binding_unavailable": "The configured provider credentials are unavailable.",
    "credential_resolution_failed": "The configured provider credentials could not be loaded safely.",
    "egress_denied": "The request was blocked by the workspace data-egress policy.",
    "egress_fake_data_attestation_invalid": (
        "The workspace fake-data attestation is invalid."
    ),
    "egress_fake_data_attestation_required": (
        "A valid workspace fake-data attestation is required."
    ),
    "egress_fake_data_attestation_revoked": (
        "The workspace fake-data attestation has been revoked."
    ),
    "egress_fake_data_attestation_scope_denied": (
        "The resource is outside the fake-data attestation scope."
    ),
    "egress_fake_data_attestation_unavailable": (
        "The workspace fake-data attestation could not be verified."
    ),
    "egress_fake_data_attestation_workspace_mismatch": (
        "The fake-data attestation belongs to another workspace."
    ),
    "egress_fake_data_classification_unverified": (
        "The resource fake-data classification could not be verified."
    ),
    "hosted_runtime_failed": "The hosted runtime could not complete the request.",
    "hosted_agent_runtime_disabled": "Hosted agentic runtime admission is disabled.",
    "google_agentic_preview_disabled": "Google agentic preview admission is disabled.",
    "openrouter_agentic_preview_disabled": "OpenRouter agentic preview admission is disabled.",
    "model_provider_unavailable": "The selected model provider is unavailable.",
    "plain_hosted_chat_model_blocks_attachments": (
        "The selected model does not support image or file attachments."
    ),
    "profile_definition_invalid": "This model profile is not currently available.",
    "provider_authentication_failed": "The model provider rejected the configured credentials.",
    "provider_budget_exceeded": "The model provider exhausted the configured token budget.",
    "provider_cancelled": "The model provider cancelled the request.",
    "provider_endpoint_parameters_unsupported": (
        "The certified provider endpoint does not support every required request parameter."
    ),
    "provider_credential_authorization_missing": "The configured provider credentials are unavailable.",
    "provider_execution_failed": "The model runtime could not complete the request.",
    "provider_mixed_text_and_tool_call": "The provider returned an incompatible text and tool-call sequence.",
    "provider_no_eligible_endpoint": "No certified provider endpoint is currently available for this model.",
    "provider_output_incomplete": "The model provider exhausted the output budget before completing the response.",
    "provider_thread_missing": (
        "The provider conversation needed to continue this chat is no longer available."
    ),
    "provider_parallel_tool_calls_forbidden": (
        "The provider returned multiple tool calls, but this profile permits only sequential execution. "
        "Those tool calls were not executed."
    ),
    "provider_quota_exceeded": "The model provider reports that the configured quota is exhausted.",
    "provider_rate_limited": "The model provider is temporarily rate-limiting requests.",
    "provider_request_rejected": "The model provider rejected the request.",
    "provider_resource_exhausted": "The model provider reports that a required resource is exhausted.",
    "provider_response_invalid": "The model provider returned an invalid response.",
    "provider_timeout": "The model provider did not respond in time.",
    "provider_tool_call_index_invalid": (
        "The provider returned an invalid tool-call sequence. That tool call was not executed."
    ),
    "provider_tool_not_declared": (
        "The model requested a tool that is not available. The unavailable tool was not executed."
    ),
    "provider_unavailable": "The model provider is temporarily unavailable.",
    "runtime_cancelled": "The runtime request was cancelled.",
    "runtime_health_unavailable": "The selected runtime is not currently healthy.",
    "runtime_actor_policy_denied": "The current actor is no longer authorized for this runtime profile.",
    "runtime_authority_unavailable": (
        "The selected runtime has no effective server-side authority snapshot."
    ),
    "runtime_profile_upgrade_required": (
        "This chat requires a compatible runtime-profile upgrade before it can continue."
    ),
    "remote_agentic_attestation_invalid": (
        "The workspace fake-data attestation is invalid."
    ),
    "remote_agentic_attestation_required": (
        "This remote profile requires a valid workspace fake-data attestation."
    ),
    "remote_agentic_attestation_revoked": (
        "The workspace fake-data attestation has been revoked."
    ),
    "remote_agentic_attestation_unavailable": (
        "Remote agentic attestation admission is not available."
    ),
    "remote_agentic_attestation_workspace_mismatch": (
        "The fake-data attestation belongs to another workspace."
    ),
    "remote_agentic_provider_unapproved": "This remote agentic provider is not approved.",
    "remote_data_declaration_not_accepted": (
        "Data classification is server-owned and cannot be declared by this request."
    ),
    "runtime_client_authority_not_accepted": (
        "Runtime classification, attestation, and egress authority are server-owned."
    ),
    "tool_execution_unknown": "The runtime could not verify whether the tool completed.",
    "tool_capability_denied": "A tool requires a capability that is not effective for this turn.",
    "tool_effect_unclassified": "A tool has no certified execution-effect classification.",
    "tool_execution_mode_denied": "A tool is not authorized in the effective execution mode.",
    "tool_not_found": (
        "The model requested a tool that is not available. The unavailable tool was not executed."
    ),
    "tool_not_authorized": "A tool is not authorized for this runtime turn.",
    "tool_schema_not_certified": "A tool schema is outside the certified runtime boundary.",
    "tool_workspace_mismatch": "A tool is outside the current workspace authority.",
    "workspace_profile_binding_disabled": "This workspace model profile is disabled.",
    "workspace_binding_disabled": "This workspace model binding is disabled.",
    "workspace_binding_missing": "This workspace has no model binding.",
}
_GENERIC_PUBLIC_MESSAGE = "The runtime could not complete this request."


def normalized_failure_reason_code(value: object, *, fallback: str) -> str:
    """Return one bounded diagnostic code without exposing raw exception text."""
    candidate = str(value or "").strip().lower()
    return candidate if _REASON_CODE.fullmatch(candidate) else fallback


def runtime_failure_public_message(reason_code: object) -> str:
    """Translate one internal reason code into stable, redaction-safe copy."""
    normalized = normalized_failure_reason_code(
        reason_code,
        fallback="runtime_execution_failed",
    )
    return _PUBLIC_MESSAGES.get(normalized, _GENERIC_PUBLIC_MESSAGE)


def public_runtime_failure_reason_code(
    reason_code: object,
    *,
    fallback: str = "runtime_authority_unavailable",
) -> str:
    """Return only a code with explicitly approved public copy."""
    normalized = normalized_failure_reason_code(reason_code, fallback=fallback)
    return normalized if normalized in _PUBLIC_MESSAGES else fallback


def runtime_failure_details(error: object) -> tuple[str, str]:
    """Return a stable code and public copy without trusting exception text."""
    reason = getattr(error, "reason_code", None)
    code = normalized_failure_reason_code(reason, fallback="runtime_execution_failed")
    return code, runtime_failure_public_message(code)


__all__ = [
    "normalized_failure_reason_code",
    "public_runtime_failure_reason_code",
    "runtime_failure_details",
    "runtime_failure_public_message",
]
