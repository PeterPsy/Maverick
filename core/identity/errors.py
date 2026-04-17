"""Identity-domain errors."""


class IdentityError(ValueError):
    """Base error for identity-domain operations."""


class UserNotFoundError(IdentityError):
    """Raised when a user cannot be resolved."""


class AuthenticationError(IdentityError):
    """Raised when credentials or sessions are invalid."""


class SessionNotFoundError(IdentityError):
    """Raised when an auth session cannot be resolved."""
