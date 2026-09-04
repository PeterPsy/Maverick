"""Server-owned attachment projection modes for workspace references."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class RuntimeAttachmentReadFence:
    """Immutable identity observed for one turn attachment reference."""

    workspace_relative_path: str
    read_encoding: str
    resource_identity: str
    resource_revision: str
    resource_digest: str

    def __post_init__(self) -> None:
        canonical = canonical_attachment_path(self.workspace_relative_path)
        if (
            canonical != self.workspace_relative_path
            or self.read_encoding not in {"utf-8", "base64"}
            or not self.resource_identity
            or not _sha256(self.resource_revision)
            or not _sha256(self.resource_digest)
        ):
            raise ValueError("agentic_attachment_fence_invalid")

    def projection(self) -> dict[str, str]:
        """Return the exact model-visible reference required by the tool schema."""
        return {
            "mode": "workspace_reference",
            "read_capability": "core-capability:filesystem.read",
            "read_encoding": self.read_encoding,
            "expected_resource_identity": self.resource_identity,
            "expected_resource_revision": self.resource_revision,
            "expected_resource_digest": self.resource_digest,
        }

    def classification_projection(
        self,
        content: object,
    ) -> dict[str, object]:
        """Remove only authenticated server-owned identity bytes before scanning."""
        if not isinstance(content, dict):
            raise ValueError("agentic_attachment_fence_invalid")
        projection = content.get("projection")
        if (
            not isinstance(projection, dict)
            or projection != self.projection()
            or content.get("workspace_relative_path")
            != self.workspace_relative_path
        ):
            raise ValueError("agentic_attachment_fence_invalid")
        classification_projection = dict(projection)
        for field_name in (
            "expected_resource_identity",
            "expected_resource_revision",
            "expected_resource_digest",
        ):
            classification_projection.pop(field_name)
        return {**content, "projection": classification_projection}


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


def canonical_attachment_path(value: object) -> str:
    """Canonicalize one relative attachment path without accepting aliases."""
    if not isinstance(value, str):
        raise ValueError("agentic_attachment_metadata_invalid")
    raw = value.strip()
    path = PurePosixPath(raw)
    if (
        not raw
        or "\\" in raw
        or "\x00" in raw
        or path.is_absolute()
        or path.as_posix() != raw
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("agentic_attachment_metadata_invalid")
    return raw


def runtime_attachment_read_fences(
    input_sources: object,
) -> tuple[RuntimeAttachmentReadFence, ...]:
    """Extract only server-owned fences from captured attachment sources."""
    fences: list[RuntimeAttachmentReadFence] = []
    seen: dict[str, RuntimeAttachmentReadFence] = {}
    for source in tuple(input_sources or ()):  # type: ignore[arg-type]
        if str(getattr(source, "provenance", "") or "") != "attachment":
            continue
        fence = getattr(source, "attachment_read_fence", None)
        if not isinstance(fence, RuntimeAttachmentReadFence):
            continue
        previous = seen.get(fence.workspace_relative_path)
        if previous is not None and previous != fence:
            raise ValueError("agentic_attachment_fence_conflict")
        if previous is None:
            seen[fence.workspace_relative_path] = fence
            fences.append(fence)
    return tuple(fences)


def attachment_read_fence_for_path(
    fences: tuple[RuntimeAttachmentReadFence, ...],
    value: object,
) -> RuntimeAttachmentReadFence | None:
    """Resolve a fence for canonical or filesystem-equivalent path spelling."""
    if not isinstance(value, str) or "\x00" in value or "\\" in value:
        return None
    raw = value.strip()
    candidate = PurePosixPath(raw)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        return None
    path = "/".join(part for part in candidate.parts if part != ".")
    for fence in fences:
        if fence.workspace_relative_path == path:
            return fence
    return None


def _sha256(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "RuntimeAttachmentReadFence",
    "attachment_read_encoding",
    "attachment_read_fence_for_path",
    "canonical_attachment_path",
    "runtime_attachment_read_fences",
]
