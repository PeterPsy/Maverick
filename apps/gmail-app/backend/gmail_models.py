"""Domain records for Gmail App."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr
import re


EMAIL_RE = re.compile(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+")
EXCLUDED_SYSTEM_LABELS = {"SPAM", "TRASH"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_email(value: str) -> str:
    _name, address = parseaddr(value)
    return address.strip().lower()


def email_domain(address: str) -> str:
    cleaned = clean_email(address)
    if "@" not in cleaned:
        return ""
    return cleaned.rsplit("@", 1)[1]


def extract_email_addresses(text: str) -> list[str]:
    found = {clean_email(match.group(0)) for match in EMAIL_RE.finditer(text or "")}
    return sorted(item for item in found if item)


def has_excluded_system_label(labels: list[str] | None) -> bool:
    return bool(EXCLUDED_SYSTEM_LABELS.intersection({str(label).upper() for label in labels or []}))


@dataclass(frozen=True)
class GmailMessage:
    id: str
    thread_id: str
    from_email: str
    to_emails: list[str]
    subject: str
    snippet: str
    body_text: str
    received_at: str
    is_unread: bool = False


@dataclass(frozen=True)
class GmailThread:
    id: str
    subject: str
    participants: list[str]
    snippet: str
    updated_at: str
    messages: list[GmailMessage]
    is_unread: bool = False
    labels: list[str] | None = None
