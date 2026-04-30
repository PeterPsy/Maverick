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
