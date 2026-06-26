"""Storage-owned MIME normalization."""

from __future__ import annotations

import mimetypes
from pathlib import Path


SUFFIX_CONTENT_TYPES = {
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".oga": "audio/ogg",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".weba": "audio/webm",
}


def normalize_content_type(content_type: object, *, file_name: object = "", suffix: object = "") -> str:
    raw = str(content_type or "").strip()
    normalized = raw.split(";", 1)[0].lower()
    extension = _suffix(file_name=file_name, suffix=suffix)
    if not normalized or normalized == "application/octet-stream":
        return guess_content_type(str(file_name or ""), suffix=extension)
    if extension == ".m4a" and normalized in {"audio/x-m4a", "audio/m4a", "video/mp4"}:
        return "audio/mp4"
    return raw


def guess_content_type(file_name: object, *, suffix: object = "") -> str:
    extension = _suffix(file_name=file_name, suffix=suffix)
    if extension in SUFFIX_CONTENT_TYPES:
        return SUFFIX_CONTENT_TYPES[extension]
    return mimetypes.guess_type(str(file_name or ""))[0] or "application/octet-stream"


def _suffix(*, file_name: object, suffix: object) -> str:
    value = str(suffix or "").strip().lower()
    if value:
        return value if value.startswith(".") else f".{value}"
    return Path(str(file_name or "")).suffix.lower()
