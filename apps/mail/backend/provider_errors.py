"""Redaction-safe provider failures and retry classification."""

import imaplib
import smtplib
import ssl


class ProviderError(ValueError):
    def __init__(self, message, *, code="provider_error", status=None, delivery_rejected=False):
        super().__init__(message)
        self.code = code
        self.status = status
        self.delivery_rejected = delivery_rejected


def error_code(error):
    if isinstance(error, ProviderError):
        return error.code
    if isinstance(error, ssl.SSLCertVerificationError):
        return "tls_verification_failed"
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return "provider_authentication"
    if isinstance(error, imaplib.IMAP4.error):
        return "provider_protocol_error"
    if isinstance(error, TimeoutError):
        return "provider_timeout"
    if isinstance(error, OSError):
        return "provider_connection_failed"
    return "local_error"
