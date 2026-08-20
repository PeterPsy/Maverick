"""Canonical redaction-safe terminal reasons emitted by agentic providers."""

from __future__ import annotations

import re


_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# This is the single trust boundary for provider-originated error events. Codecs
# may emit only these public, bounded categories; the hosted loop consumes the
# same registry instead of maintaining a second provider-specific allowlist.
AGENTIC_PROVIDER_TERMINAL_REASON_CODES = frozenset(
    {
        "provider_authentication_failed",
        "provider_budget_exceeded",
        "provider_cancelled",
        "provider_endpoint_parameters_unsupported",
        "provider_mixed_text_and_tool_call",
        "provider_no_eligible_endpoint",
        "provider_output_incomplete",
        "provider_parallel_tool_calls_forbidden",
        "provider_private_codec_mismatch",
        "provider_private_integrity_failed",
        "provider_private_quota_exceeded",
        "provider_private_size_invalid",
        "provider_private_state_invalid",
        "provider_private_state_unavailable",
        "provider_quota_exceeded",
        "provider_rate_limited",
        "provider_request_invalid",
        "provider_request_rejected",
        "provider_resource_exhausted",
        "provider_response_invalid",
        "provider_routing_not_certified",
        "provider_timeout",
        "provider_tool_call_index_invalid",
        "provider_tool_not_declared",
        "provider_tool_result_pairing_invalid",
        "provider_unavailable",
        "provider_upstream_not_certified",
    }
)


def normalized_agentic_provider_reason(value: object) -> str:
    """Return a registered provider reason or the fail-closed generic code."""
    candidate = str(value or "").strip().lower()
    if (
        not _REASON_CODE.fullmatch(candidate)
        or candidate not in AGENTIC_PROVIDER_TERMINAL_REASON_CODES
    ):
        return "provider_response_invalid"
    return candidate


__all__ = [
    "AGENTIC_PROVIDER_TERMINAL_REASON_CODES",
    "normalized_agentic_provider_reason",
]
