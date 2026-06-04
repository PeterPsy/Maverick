"""Verified immutable content storage for Memory source bodies and chunks."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from errors import MemoryValidationError


CONTENT_ROOT_NAME = "content"
CONTENT_KINDS = {"sources", "chunks"}


@dataclass(frozen=True)
class ContentRecord:
    kind: str
    relative_path: str
    body_sha256: str
    body_bytes: int


def canonical_body(body_markdown: str) -> str:
    body = str(body_markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    if body and not body.endswith("\n"):
        return f"{body}\n"
    return body


def body_hash(body_markdown: str) -> str:
    return sha256(canonical_body(body_markdown).encode("utf-8")).hexdigest()


def write_body(
    data_root: Path,
    *,
    kind: str,
    body_markdown: str,
    metadata: dict[str, Any] | None = None,
) -> ContentRecord:
    normalized_kind = normalize_kind(kind)
    body = canonical_body(body_markdown)
    digest = body_hash(body)
    relative_path = content_relative_path(normalized_kind, digest)
    target = resolve_content_path(data_root, relative_path)
    payload = stored_payload(body, metadata=metadata)
    if target.exists():
        stored_body = read_body(data_root, relative_path=relative_path, expected_sha256=digest)
        if stored_body != body:
            raise MemoryValidationError("content store hash path contains different body content.")
        return ContentRecord(
            kind=normalized_kind,
            relative_path=relative_path,
            body_sha256=digest,
            body_bytes=len(body.encode("utf-8")),
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, prefix=".maverick-memory-write-", delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)
    return ContentRecord(
        kind=normalized_kind,
        relative_path=relative_path,
        body_sha256=digest,
        body_bytes=len(body.encode("utf-8")),
    )


def read_body(data_root: Path, *, relative_path: str, expected_sha256: str | None = None) -> str:
    path = resolve_content_path(data_root, relative_path)
    try:
        payload = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise MemoryValidationError("content store body not found.") from error
    body = parse_stored_body(payload)
    actual_sha256 = body_hash(body)
    expected = str(expected_sha256 or Path(relative_path).stem or "").strip()
    if expected and actual_sha256 != expected:
        raise MemoryValidationError("content store body hash mismatch.")
    return body


def content_relative_path(kind: str, digest: str) -> str:
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise MemoryValidationError("content hash must be a lowercase sha256 hex digest.")
    return f"{CONTENT_ROOT_NAME}/{kind}/{digest[:2]}/{digest}.md"


def resolve_content_path(data_root: Path, relative_path: str) -> Path:
    normalized = normalize_relative_path(relative_path)
    content_root = (data_root / CONTENT_ROOT_NAME).resolve(strict=False)
    resolved = (data_root / normalized).resolve(strict=False)
    if content_root != resolved and content_root not in resolved.parents:
        raise MemoryValidationError("content store path must stay under data/memory/content.")
    return resolved


def normalize_relative_path(relative_path: str) -> Path:
    raw_path = Path(str(relative_path or ""))
    if raw_path.is_absolute():
        raise MemoryValidationError("content store path must be relative.")
    if ".." in raw_path.parts:
        raise MemoryValidationError("content store path must not contain traversal segments.")
    parts = raw_path.parts
    if len(parts) != 4 or parts[0] != CONTENT_ROOT_NAME or parts[1] not in CONTENT_KINDS or raw_path.suffix != ".md":
        raise MemoryValidationError("content store path must target content/sources or content/chunks markdown.")
    return raw_path


def normalize_kind(kind: str) -> str:
    normalized = str(kind or "").strip()
    if normalized not in CONTENT_KINDS:
        raise MemoryValidationError("content kind must be sources or chunks.")
    return normalized


def stored_payload(body: str, *, metadata: dict[str, Any] | None) -> str:
    encoded_metadata = json.dumps(metadata or {}, sort_keys=True, ensure_ascii=False)
    return f"---\n{encoded_metadata}\n---\n{body}"


def parse_stored_body(payload: str) -> str:
    if not payload.startswith("---\n"):
        return payload
    marker = "\n---\n"
    marker_index = payload.find(marker, 4)
    if marker_index == -1:
        return payload
    return payload[marker_index + len(marker) :]
