"""Canonical Project IR JSON and content-addressed identity."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented by the IR canonical profile."""


def canonical_dumps(value: Any) -> str:
    """Serialize JSON using sorted keys, UTF-8 text, and no insignificant space."""

    _validate_json_value(value, path="")
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise CanonicalizationError("Value is not canonical Project IR JSON.") from error


def canonical_bytes(value: Any) -> bytes:
    return canonical_dumps(value).encode("utf-8")


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def canonical_copy(value: Any) -> Any:
    """Return a detached JSON value normalized through canonical serialization."""

    return json.loads(canonical_dumps(value))


def _validate_json_value(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        raise CanonicalizationError(
            f"Floating-point numbers are not allowed in Project IR at `{path or '/'}`."
        )
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}/{index}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("Project IR object keys must be strings.")
            _validate_json_value(item, path=f"{path}/{_escape(key)}")
        return
    raise CanonicalizationError(
        f"Unsupported Project IR value `{type(value).__name__}` at `{path or '/'}`."
    )


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
