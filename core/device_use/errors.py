"""Stable failures for the native device-use bridge."""

from __future__ import annotations


class DeviceUseError(RuntimeError):
    """Base device-use error with a public, redaction-safe reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class DeviceUseAuthorizationError(DeviceUseError):
    """The caller does not own the requested activation."""


class DeviceUseUnavailableError(DeviceUseError):
    """No compatible native executor can safely accept the operation."""


class DeviceUseExecutionUnknownError(DeviceUseError):
    """The transport failed after dispatch and the physical outcome is unknown."""
