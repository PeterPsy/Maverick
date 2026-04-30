"""Runtime attachment prompt materialization."""

from __future__ import annotations

from pathlib import Path, PurePosixPath


def input_text_with_attachment_links(*, input_text: str, attachments: list[dict[str, object]] | None, workspace_root: str) -> str:
    """Append workspace file links so providers can inspect uploaded files."""
    if not attachments:
        return input_text

    attachment_lines = [_attachment_line(attachment=attachment, workspace_root=workspace_root) for attachment in attachments]
    visible_lines = [line for line in attachment_lines if line]
    if not visible_lines:
        return input_text

    base_text = input_text.strip() or "Please inspect the uploaded attachment(s)."
    return "\n".join(
        [
            base_text,
            "",
            "Uploaded attachments:",
            *visible_lines,
            "",
            "Use the workspace-relative path or local path above when you need to inspect an uploaded file.",
        ]
    )


def _attachment_line(*, attachment: dict[str, object], workspace_root: str) -> str:
    relative_path = _safe_workspace_relative_path(_string_value(attachment.get("relativePath") or attachment.get("relative_path")))
    name = _string_value(attachment.get("name")) or (Path(relative_path).name if relative_path else "uploaded file")
    content_type = _string_value(attachment.get("type") or attachment.get("content_type"))
    size = attachment.get("size") or attachment.get("size_bytes")
    details = ", ".join(item for item in [content_type, _size_label(size)] if item)

    if not relative_path:
        return f"- {name}" + (f" ({details})" if details else "")

    local_path = _local_path(workspace_root=workspace_root, relative_path=relative_path)
    suffix = f" ({details})" if details else ""
    return f"- {name}{suffix}: {relative_path}; local path: {local_path}"


def _safe_workspace_relative_path(value: str) -> str:
    if not value:
        return ""
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return ""
    if len(path.parts) < 3 or path.parts[0] != "storage" or path.parts[1] not in {"uploaded", "generated"}:
        return ""
    return path.as_posix()


def _local_path(*, workspace_root: str, relative_path: str) -> str:
    root = Path(workspace_root).resolve()
    candidate = (root / PurePosixPath(relative_path)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return str(root)
    return str(candidate)


def _size_label(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    amount = int(value)
    if amount < 0:
        return ""
    return f"{amount} bytes"


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
