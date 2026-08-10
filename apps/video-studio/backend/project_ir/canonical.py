"""Canonical Project IR JSON and content-addressed identity."""

from __future__ import annotations

import hashlib
import json
from typing import Any


MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_NESTING_DEPTH = 64


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
    except (RecursionError, TypeError, ValueError) as error:
        raise CanonicalizationError("Value is not canonical Project IR JSON.") from error


def canonical_bytes(value: Any) -> bytes:
    return canonical_dumps(value).encode("utf-8")


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def canonical_copy(value: Any) -> Any:
    """Return a detached JSON value normalized through canonical serialization."""

    return json.loads(canonical_dumps(value))


def _validate_json_value(value: Any, *, path: str) -> None:
    pending: list[tuple[Any, str, int]] = [(value, path, 0)]
    while pending:
        current, current_path, depth = pending.pop()
        display_path = current_path or "/"
        if depth > MAX_NESTING_DEPTH:
            raise CanonicalizationError(
                f"Project IR nesting exceeds {MAX_NESTING_DEPTH} levels at `{display_path}`."
            )
        if current is None or isinstance(current, bool):
            continue
        if isinstance(current, int):
            if not -MAX_SAFE_INTEGER <= current <= MAX_SAFE_INTEGER:
                raise CanonicalizationError(
                    f"Integer authority exceeds the cross-platform safe range at `{display_path}`."
                )
            continue
        if isinstance(current, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in current):
                raise CanonicalizationError(
                    f"Unicode surrogate code points are not allowed at `{display_path}`."
                )
            continue
        if isinstance(current, float):
            raise CanonicalizationError(
                f"Floating-point numbers are not allowed in Project IR at `{display_path}`."
            )
        if isinstance(current, list):
            pending.extend(
                (item, f"{current_path}/{index}", depth + 1)
                for index, item in reversed(tuple(enumerate(current)))
            )
            continue
        if isinstance(current, dict):
            for key in current:
                if not isinstance(key, str):
                    raise CanonicalizationError("Project IR object keys must be strings.")
            pending.extend(
                (item, f"{current_path}/{_escape(key)}", depth + 1)
                for key, item in reversed(tuple(current.items()))
            )
            continue
        raise CanonicalizationError(
            f"Unsupported Project IR value `{type(current).__name__}` at `{display_path}`."
        )


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
