"""Core-owned conservative data classification for transient runtime bytes."""

from __future__ import annotations

import json
import re

from core.egress.agentic_transforms import canonical_egress_content
from core.runtime.output_compaction.redaction import redact_payload, redact_text


_SSN_PATTERN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"
)
_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]\d{4}(?!\d)"
)
_PAYMENT_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def classify_runtime_content(
    content: object,
    *,
    content_type: str,
    max_bytes: int = 1_500_000,
) -> str:
    """Classify exact transient bytes without promoting from source ownership."""
    encoded = canonical_egress_content(content)
    if len(encoded) > max_bytes:
        return "unclassified"
    try:
        text = encoded.decode("utf-8")
    except UnicodeDecodeError:
        return "unclassified"
    if content_type == "application/json":
        try:
            structured = json.loads(text)
        except json.JSONDecodeError:
            return "unclassified"
        if redact_payload(structured) != structured:
            return "credential_or_secret"
    if redact_text(text) != text:
        return "credential_or_secret"
    if _SSN_PATTERN.search(text) or any(
        _luhn_valid(match.group(0))
        for match in _PAYMENT_CARD_CANDIDATE.finditer(text)
    ):
        return "regulated_or_customer_data"
    if _EMAIL_PATTERN.search(text) or _PHONE_PATTERN.search(text):
        return "personal_data"
    return "public"


def _luhn_valid(value: str) -> bool:
    digits = [int(character) for character in value if character.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


__all__ = ["classify_runtime_content"]
