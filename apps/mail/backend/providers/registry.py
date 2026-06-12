"""Provider selection helpers for Mail."""

from __future__ import annotations

from pathlib import Path

from store import resolve_connected_connection

from .base import MailProvider
from .gmail import GmailProvider
from .imap_smtp import ImapSmtpProvider


def provider_for_connection(data_root: Path, connection_id: str | None) -> MailProvider:
    if not connection_id:
        return GmailProvider()
    connection = resolve_connected_connection(data_root, connection_id)
    return provider_by_id(str(connection["provider"]))


def provider_by_id(provider_id: str) -> MailProvider:
    if provider_id == "gmail":
        return GmailProvider()
    if provider_id == "imap_smtp":
        return ImapSmtpProvider()
    raise ValueError(f"Unsupported mail provider `{provider_id}`")
