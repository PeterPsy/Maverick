"""Core-owned conservative data classification for transient runtime bytes."""

from __future__ import annotations

import json
import re

from core.egress.agentic_transforms import canonical_egress_content
from core.egress.classification import (
    CanonicalSourceClassification,
    join_classifications,
    join_data_classes,
    validated_classification,
)
from core.runtime.output_compaction.redaction import redact_payload, redact_text


_SSN_PATTERN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"
)
_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]\d{4}(?!\d)"
)
_PAYMENT_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
MAX_RUNTIME_CONTENT_CLASSIFICATION_BYTES = 1_500_000


def classify_runtime_content(
    content: object,
    *,
    content_type: str,
    max_bytes: int = MAX_RUNTIME_CONTENT_CLASSIFICATION_BYTES,
) -> str:
    """Classify exact transient bytes without promoting from source ownership."""
    encoded = canonical_egress_content(content)
    if len(encoded) > max_bytes:
        return "unclassified"
    try:
        text = encoded.decode("utf-8")
    except UnicodeDecodeError:
        if content_type != "application/octet-stream":
            return "unclassified"
        # Binary filesystem reads still need marker detection over the original
        # bytes before their base64 transport projection. Replacement decoding
        # preserves every ASCII marker while refusing to interpret the payload
        # as structured text.
        text = encoded.decode("utf-8", errors="replace")
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
    # Absence of a known sensitive marker is not authoritative evidence that
    # arbitrary content is public.  Callers that need a public classification
    # must resolve one from an explicit, version-bound source of authority.
    return "unclassified"


def narrow_runtime_content_classification(
    classification: CanonicalSourceClassification,
    content: object,
    *,
    content_type: str,
) -> CanonicalSourceClassification:
    """Apply exact-byte marker detection without ever promoting source authority."""
    normalized = join_classifications((classification,)).sources[0]
    detected = classify_runtime_content(content, content_type=content_type)
    if detected == "unclassified":
        return normalized
    return validated_classification(
        data_class=join_data_classes((normalized.data_class, detected)),
        provenance=normalized.provenance,
        trust_level=normalized.trust_level,
        source_ref=normalized.source_ref,
        source_revision=normalized.source_revision,
        source_digest=normalized.source_digest,
        resource_identity=normalized.resource_identity,
        classification_revision=normalized.classification_revision,
        classification_authority_id=normalized.classification_authority_id,
        classification_authority_kind=normalized.classification_authority_kind,
        classification_authority_ref=normalized.classification_authority_ref,
        classification_authority_revision=(
            normalized.classification_authority_revision
        ),
        classification_authority_digest=(
            normalized.classification_authority_digest
        ),
        classification_authority_policy_revision=(
            normalized.classification_authority_policy_revision
        ),
        classification_authority_bound=(
            normalized.classification_authority_bound
        ),
    )


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
__all__ = [
    "MAX_RUNTIME_CONTENT_CLASSIFICATION_BYTES",
    "classify_runtime_content",
    "narrow_runtime_content_classification",
]
