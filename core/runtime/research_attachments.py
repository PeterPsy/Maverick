"""Bounded inline snapshots of user-selected Storage attachments for Research."""

from __future__ import annotations

import base64
from pathlib import PurePosixPath

from core.providers.errors import AgenticRuntimeError
from core.runtime.attachment_projection import canonical_attachment_path


MAX_RESEARCH_ATTACHMENTS = 8
MAX_RESEARCH_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_RESEARCH_ATTACHMENTS_TOTAL_BYTES = 50 * 1024 * 1024
MAX_RESEARCH_ATTACHMENT_TEXT_CHARS = 200_000
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".odt"}
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml"}


def validate_research_attachments(attachments) -> None:
    if not isinstance(attachments, (list, tuple)) or len(attachments) > MAX_RESEARCH_ATTACHMENTS:
        raise AgenticRuntimeError("research_attachment_limit_exceeded")
    for attachment in attachments:
        if not isinstance(attachment, dict):
            raise AgenticRuntimeError("agentic_attachment_metadata_invalid")
        try:
            path = canonical_attachment_path(
                attachment.get("relativePath") or attachment.get("relative_path")
            )
        except ValueError as error:
            raise AgenticRuntimeError("agentic_attachment_metadata_invalid") from error
        if PurePosixPath(path).parts[:2] not in {
            ("storage", "uploaded"), ("storage", "generated"),
        } or len(PurePosixPath(path).parts) < 3:
            raise AgenticRuntimeError("agentic_attachment_metadata_invalid")


def materialize_research_attachment(
    state, *, session, attachment, media_type, filesystem, fence,
) -> dict[str, object]:
    validate_research_attachments([attachment])
    if filesystem is None or fence is None:
        raise AgenticRuntimeError("research_attachment_unavailable")
    result = filesystem.read_bytes(
        fence.workspace_relative_path,
        max_bytes=MAX_RESEARCH_ATTACHMENT_BYTES + 1,
        expected_resource_identity=fence.resource_identity,
        expected_resource_revision=fence.resource_revision,
        expected_resource_digest=fence.resource_digest,
    )
    raw = base64.b64decode(result.payload["content_base64"], validate=True)
    if result.payload["truncated"] or len(raw) > MAX_RESEARCH_ATTACHMENT_BYTES:
        raise AgenticRuntimeError("research_attachment_limit_exceeded")
    filename = PurePosixPath(fence.workspace_relative_path).name
    content: dict[str, object] = {
        "name": filename, "media_type": media_type, "size_bytes": len(raw),
        "projection": {"mode": "inline"},
    }
    if media_type.startswith("image/"):
        content["data"] = base64.b64encode(raw).decode("ascii")
    elif PurePosixPath(filename).suffix.lower() in DOCUMENT_EXTENSIONS:
        from core.apps.runtime_attachment_text import extract_runtime_attachment_text

        content["text"] = extract_runtime_attachment_text(
            state, session=session, filename=filename, raw=raw,
            max_chars=MAX_RESEARCH_ATTACHMENT_TEXT_CHARS,
        )
    elif (
        media_type.startswith("text/") or media_type == "application/json"
        or PurePosixPath(filename).suffix.lower() in TEXT_EXTENSIONS
    ):
        try:
            content["text"] = raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise AgenticRuntimeError("research_attachment_text_invalid") from error
    else:
        raise AgenticRuntimeError("agentic_attachment_modality_not_supported")
    if isinstance(content.get("text"), str) and len(content["text"]) > MAX_RESEARCH_ATTACHMENT_TEXT_CHARS:
        raise AgenticRuntimeError("research_attachment_limit_exceeded")
    return content


def validate_inline_attachment(source) -> dict[str, object]:
    content = getattr(source, "content", None)
    if (
        getattr(source, "projection_mode", None) != "inline"
        or not isinstance(content, dict)
        or content.get("projection") != {"mode": "inline"}
        or set(content) not in (
            {"name", "media_type", "size_bytes", "projection", "text"},
            {"name", "media_type", "size_bytes", "projection", "data"},
        )
        or content.get("media_type") != getattr(source, "capability_modality", None)
        or not isinstance(content.get("media_type"), str)
        or not isinstance(content.get("name"), str)
        or not isinstance(content.get("size_bytes"), int)
        or isinstance(content.get("size_bytes"), bool)
        or not 0 <= content["size_bytes"] <= MAX_RESEARCH_ATTACHMENT_BYTES
    ):
        raise AgenticRuntimeError("agentic_attachment_metadata_invalid")
    if "data" in content:
        if (
            not str(content["media_type"]).startswith("image/")
            or not isinstance(content["data"], str)
            or len(content["data"]) > ((MAX_RESEARCH_ATTACHMENT_BYTES + 2) // 3) * 4
        ):
            raise AgenticRuntimeError("agentic_attachment_metadata_invalid")
    elif (
        not isinstance(content.get("text"), str)
        or len(content["text"]) > MAX_RESEARCH_ATTACHMENT_TEXT_CHARS
    ):
        raise AgenticRuntimeError("agentic_attachment_metadata_invalid")
    return content


def research_input_text(input_text: str, sources) -> str:
    sections = [input_text.strip() or "Please analyze the uploaded attachments."]
    for source in sources:
        if source.provenance == "attachment":
            content = validate_inline_attachment(source)
            if "text" in content:
                sections.append(f"[Uploaded attachment: {content['name']}]\n{content['text']}")
    return "\n\n".join(sections) if len(sections) > 1 else input_text


def research_image_contents(sources) -> tuple[dict[str, object], ...]:
    return tuple(
        content for source in sources if source.provenance == "attachment"
        if "data" in (content := validate_inline_attachment(source))
    )
