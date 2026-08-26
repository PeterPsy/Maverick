"""Allowlisted runtime status reasons for untrusted API and app projections."""

from __future__ import annotations


PUBLIC_RUNTIME_RECOVERY_REASON_CODES = frozenset(
    {
        "remote_agentic_state_ambiguous",
        "runtime_state_ambiguous",
    }
)


def public_runtime_recovery_reason_code(
    *,
    status: object,
    reason_code: object,
) -> str | None:
    """Return only a stable public cause for a quarantined runtime session."""
    if str(status or "").strip() != "recovery_required":
        return None
    normalized = str(reason_code or "").strip()
    if normalized in PUBLIC_RUNTIME_RECOVERY_REASON_CODES:
        return normalized
    return "runtime_state_ambiguous"
