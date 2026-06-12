"""Mail provider adapters."""

from __future__ import annotations

from .base import MailProvider, ProviderCapability
from .gmail import GmailProvider

__all__ = ["GmailProvider", "MailProvider", "ProviderCapability"]
