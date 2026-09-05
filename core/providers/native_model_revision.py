"""Native revision guarantees must be supported by the actual launch transport."""

from core.providers.errors import CapabilityCertificateError


def require_native_model_revision_transport(binding) -> None:
    # Current Codex app-server and Gemini ACP integrations select model aliases,
    # not provider revisions. Preserve exact metadata but never promise to run it.
    if getattr(binding, "model_revision_policy", "provider_alias") == "exact":
        raise CapabilityCertificateError("native_agent_exact_revision_unsupported")


__all__ = ["require_native_model_revision_transport"]
