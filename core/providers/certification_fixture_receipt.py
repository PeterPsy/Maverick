"""Mandatory conformance cannot pass through an empty or skipped unittest run."""

import re

from core.providers.errors import CapabilityCertificateError


def fixture_receipt(stderr: bytes) -> dict[str, int]:
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
