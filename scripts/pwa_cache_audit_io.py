"""Strict file and scalar readers for the PWA operational policy audit."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


def load_json(path: Path, errors: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        errors.append(f"{path}: {error}")
        return None


def read_text(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        errors.append(f"{path}: {error}")
        return ""


def object_field(payload: dict[str, Any], name: str, errors: list[str]) -> dict[str, Any]:
    value = payload.get(name)
    if isinstance(value, dict):
        return value
    errors.append(f"operational policy `{name}` must be an object")
    return {}


def integer_field(payload: dict[str, Any], name: str, errors: list[str]) -> int | None:
    value = payload.get(name)
    if positive_integer(value):
        return value
    errors.append(f"operational policy `{name}` must be a positive integer")
    return None


def typescript_integer_constant(path: Path, name: str) -> int | None:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(rf"export const {re.escape(name)}\s*=\s*([0-9_ *]+);", source)
    if not match:
        return None
    factors = [part.strip().replace("_", "") for part in match.group(1).split("*")]
    if not all(part.isdigit() for part in factors):
        return None
    result = 1
    for factor in factors:
        result *= int(factor)
    return result


def positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def positive_or_zero_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
