"""Small helpers for Maverick service environment files."""

from __future__ import annotations

from pathlib import Path


def read_env_file(path: Path) -> dict[str, str]:
    """Read a simple KEY=VALUE environment file without shell expansion."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = unquote_env_value(value.strip())
    return values


def quote_env_value(value: str) -> str:
    """Quote one env value when it contains shell-sensitive characters."""
    if value and all(character.isalnum() or character in "._-/:@%" for character in value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def unquote_env_value(value: str) -> str:
    """Unquote one env value written by quote_env_value."""
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value
