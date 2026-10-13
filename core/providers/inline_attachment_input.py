"""Decode server-materialized attachment blocks after governed egress."""

from __future__ import annotations

import json
from types import SimpleNamespace

from core.runtime.research_attachments import validate_inline_attachment


def inline_attachment_content(block) -> dict[str, object] | None:
    if block.provenance != "attachment" or block.content_type != "application/json":
        return None
    content = json.loads(block.content)
    if not isinstance(content, dict) or content.get("projection") != {"mode": "inline"}:
        return None
    return validate_inline_attachment(SimpleNamespace(
        content=content, projection_mode="inline", capability_modality=content.get("media_type"),
    ))
