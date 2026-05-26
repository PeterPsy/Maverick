"""Mail provider adapters."""

from __future__ import annotations

from .base import MailProvider, ProviderCapability
from .gmail import GmailProvider
from .mock import MockMailProvider

__all__ = ["GmailProvider", "MailProvider", "MockMailProvider", "ProviderCapability"]
