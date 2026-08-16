"""Ephemeral content serialization and redaction for agentic egress."""

from __future__ import annotations

import json
from pathlib import Path
import re

from core.runtime.output_compaction.redaction import redact_payload, redact_text


_HOST_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9:])/(?:home|root|etc|var|tmp|opt|srv|usr|run)/(?:[^\s\"'<>]+)"
)


def canonical_egress_content(content: object) -> bytes:
    """Serialize one egress block deterministically without persisting it."""
    if isinstance(content, bytes):
        return bytes(content)
    if isinstance(content, str):
        return content.encode("utf-8")
    try:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("Agentic egress content must be JSON-compatible.") from error


def transform_exportable_content(
    source: bytes,
    *,
    content_type: str,
    workspace_id: str,
    workspace_root: Path | None,
    allow_sensitive_transform: bool,
) -> tuple[bytes | None, str | None, str | None]:
    """Rewrite workspace paths and redact known secret patterns in memory."""
    if not content_type.startswith("text/") and content_type != "application/json":
        return source, None, None
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError:
        return None, None, "egress_text_invalid"
    transformations: list[str] = []
    if workspace_root is not None:
        root = str(workspace_root.resolve(strict=False)).rstrip("/")
        if root and root in text:
            text = text.replace(root, f"workspace://{workspace_id}")
            transformations.append("workspace_path_reference")
    if _HOST_PATH_PATTERN.search(text):
        return None, None, "egress_host_path_detected"
    if content_type == "application/json":
        try:
            structured = json.loads(text)
        except json.JSONDecodeError:
            return None, None, "egress_json_invalid"
        redacted_value = redact_payload(structured)
        redacted = json.dumps(
            redacted_value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    else:
        redacted = redact_text(text)
    if redacted != text:
        if not allow_sensitive_transform:
            return None, None, "egress_sensitive_content_detected"
        text = redacted
        transformations.append("sensitive_text_redaction")
    return text.encode("utf-8"), "+".join(transformations) or None, None
