"""Small shared helpers for the direct full-access filesystem facade."""

from __future__ import annotations

import base64
import hashlib
import json
import stat

from core.runtime.tool_errors import RuntimeToolError


def require_expected(observation, identity, revision, digest=None) -> None:
    if identity is not None and (
        observation is None or observation.resource_identity != identity
    ):
        raise RuntimeToolError("filesystem_resource_changed")
    if revision is not None and (
        observation is None or observation.resource_revision != revision
    ):
        raise RuntimeToolError("filesystem_resource_changed")
    if digest is not None and (
        observation is None or observation.resource_digest != digest
    ):
        raise RuntimeToolError("filesystem_resource_changed")


def decode_utf8(value: bytes) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeToolError("filesystem_read_not_utf8") from error


def file_digest(path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise RuntimeToolError("filesystem_read_failed") from error
    return digest.hexdigest()


def stat_revision(value) -> str:
    return hashlib.sha256(
        ":".join(
            str(item)
            for item in (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )
        ).encode("ascii")
    ).hexdigest()


def file_type(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "other"


def cursor(offset: int, digest: str) -> str:
    raw = json.dumps(
        {"offset": offset, "digest": digest},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def cursor_state(value) -> tuple[int, str | None]:
    """Decode a cursor before a streaming scan has calculated its digest."""
    if value is None:
        return 0, None
    try:
        raw = base64.urlsafe_b64decode(str(value) + "=" * (-len(str(value)) % 4))
        payload = json.loads(raw)
        offset = int(payload["offset"])
        digest = str(payload["digest"])
        if (
            offset < 0
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError
        return offset, digest
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise RuntimeToolError("filesystem_cursor_invalid") from error


__all__ = [
    "cursor",
    "cursor_state",
    "decode_utf8",
    "file_digest",
    "file_type",
    "require_expected",
    "stat_revision",
]
