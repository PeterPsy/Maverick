"""Mandatory conformance rejects skipped tests and uncaught background failures."""

import re

from core.providers.errors import CapabilityCertificateError


def fixture_receipt(stderr: bytes) -> dict[str, int]:
    # unittest can exit zero after an uncaught thread/destructor/task exception.
    # Check the whole retained stream, not only its green footer. A deliberate
    # failure test must capture its own diagnostic instead of polluting evidence.
    if any(marker in stderr for marker in (
        b"Traceback (most recent call last)",
        b"Exception in thread",
        b"Exception ignored in:",
        b"Task exception was never retrieved",
        b"Task was destroyed but it is pending",
        b"was never awaited",
    )):
        raise CapabilityCertificateError("certification_fixture_receipt_invalid")
    # Only the standard runner's final footer, never arbitrary earlier log text.
    footer = stderr[-2_048:].decode("utf-8", errors="replace")
    match = re.search(r"(?:^|\n)Ran ([1-9][0-9]*) tests? in [0-9.]+s\n\nOK\s*\Z", footer)
    if match is None:
        raise CapabilityCertificateError("certification_fixture_receipt_invalid")
    return {"tests_run": int(match.group(1)), "skipped": 0}


def validate_fixture_receipt(receipt):
    if (not isinstance(receipt, dict) or set(receipt) != {"tests_run", "skipped"}
            or type(receipt["tests_run"]) is not int or receipt["tests_run"] <= 0
            or type(receipt["skipped"]) is not int or receipt["skipped"] != 0):
        raise CapabilityCertificateError("certification_fixture_receipt_invalid")
