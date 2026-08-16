"""Provider-domain errors."""

from __future__ import annotations


class ProviderError(Exception):
    """Base error for provider-domain failures."""


class ProviderNotFoundError(ProviderError):
    """Raised when one provider definition cannot be found."""


class ProviderDisabledError(ProviderError):
    """Raised when one provider is present but not active."""


class ProviderCredentialBindingError(ProviderError):
    """Raised when credential binding state is missing or invalid."""


class ProviderSelectionError(ProviderError):
    """Raised when provider selection cannot be resolved safely."""


class ProviderCapabilityError(ProviderError):
    """Raised when one provider cannot satisfy the requested capability."""


class ProviderLaunchError(ProviderError):
    """Raised when one runtime backend cannot be prepared for launch."""


class ProviderUsageUnavailableError(ProviderError):
    """Raised when a provider cannot return redaction-safe subscription usage."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason or "provider_unavailable")
        super().__init__(self.reason)


class AgenticProfileError(ProviderError):
    """Raised when an agentic definition or workspace binding is invalid."""


class AgenticProfileConflictError(AgenticProfileError):
    """Raised when an immutable record or expected revision conflicts."""


class CapabilityCertificateError(ProviderError):
    """Raised when certification cannot grant runtime authority."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = str(reason_code or "certificate_invalid")
        super().__init__(self.reason_code)


class CapabilityCertificateConflictError(CapabilityCertificateError):
    """Raised when immutable evidence/certificate or status CAS conflicts."""
