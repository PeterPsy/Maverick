"""Server-owned attachment projection modes for workspace references."""

from __future__ import annotations


_TEXTUAL_APPLICATION_TYPES = {
    "application/graphql",
    "application/javascript",
    "application/json",
    "application/sql",
    "application/toml",
    "application/x-javascript",
    "application/x-yaml",
    "application/xml",
    "application/yaml",
}


def attachment_read_encoding(media_type: str) -> str:
    """Return the exact filesystem.read encoding required for this MIME."""
    normalized = str(media_type or "").strip().lower().split(";", 1)[0]
    if (
        normalized.startswith("text/")
        or normalized in _TEXTUAL_APPLICATION_TYPES
        or normalized.endswith("+json")
        or normalized.endswith("+xml")
    ):
        return "utf-8"
    return "base64"


__all__ = ["attachment_read_encoding"]
