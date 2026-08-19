"""Stable public messages for structured runtime failure codes."""

from __future__ import annotations

import re


_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PUBLIC_MESSAGES = {
    "agent_step_limit_reached": "The runtime reached its step limit before completing the request.",
    "agent_tool_call_limit_reached": "The runtime reached its tool-call limit before completing the request.",
    "certificate_revoked": "This model profile is no longer authorized.",
    "credential_binding_unavailable": "The configured provider credentials are unavailable.",
    "credential_resolution_failed": "The configured provider credentials could not be loaded safely.",
    "egress_denied": "The request was blocked by the workspace data-egress policy.",
    "hosted_runtime_failed": "The hosted runtime could not complete the request.",
    "plain_hosted_chat_model_blocks_attachments": (
        "The selected model does not support image or file attachments."
    ),
    "profile_definition_invalid": "This model profile is not currently available.",
    "provider_authentication_failed": "The model provider rejected the configured credentials.",
    "provider_credential_authorization_missing": "The configured provider credentials are unavailable.",
    "provider_execution_failed": "The model runtime could not complete the request.",
    "provider_mixed_text_and_tool_call": "The provider returned an incompatible text and tool-call sequence.",
    "provider_no_eligible_endpoint": "No certified provider endpoint is currently available for this model.",
    "provider_parallel_tool_calls_forbidden": (
        "The provider returned multiple tool calls, but this profile permits only sequential execution. "
        "Those tool calls were not executed."
    ),
    "provider_rate_limited": "The model provider is temporarily rate-limiting requests.",
    "provider_request_rejected": "The model provider rejected the request.",
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
    "tool_execution_unknown": "The runtime could not verify whether the tool completed.",
    "tool_not_found": (
        "The model requested a tool that is not available. The unavailable tool was not executed."
    ),
    "workspace_profile_binding_disabled": "This workspace model profile is disabled.",
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


def runtime_failure_details(error: object) -> tuple[str, str]:
    """Return a stable code and public copy without trusting exception text."""
    reason = getattr(error, "reason_code", None)
    code = normalized_failure_reason_code(reason, fallback="runtime_execution_failed")
    return code, runtime_failure_public_message(code)


__all__ = [
    "normalized_failure_reason_code",
    "runtime_failure_details",
    "runtime_failure_public_message",
]
