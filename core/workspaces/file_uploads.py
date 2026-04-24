"""Workspace-owned file upload helpers."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import UTC, datetime
import base64
import hashlib
import re
from pathlib import Path
from uuid import uuid4

from core.workspaces.paths import workspace_paths


SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class WorkspaceUploadedFile:
    """Public metadata for one workspace uploaded file."""

    file_id: str
    workspace_id: str
    relative_path: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime

    def as_payload(self) -> dict[str, object]:
        return asdict(self)


def _safe_filename(filename: str) -> str:
    candidate = SAFE_NAME_PATTERN.sub("-", filename.strip()).strip(".-")
    return candidate or "upload.bin"


def save_workspace_upload(
    *,
    workspace_id: str,
    filename: str,
    content_type: str,
    content_base64: str,
    start_path: Path | None = None,
) -> WorkspaceUploadedFile:
    """Persist one base64-encoded upload under workspace storage/uploaded."""
    raw = base64.b64decode(content_base64.encode("ascii"), validate=True)
    file_id = str(uuid4())
    safe_name = _safe_filename(filename)
    paths = workspace_paths(workspace_id=workspace_id, start_path=start_path)
    target_dir = paths.uploaded_storage / file_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_name
    target.write_bytes(raw)
    relative_path = target.relative_to(paths.root).as_posix()
    return WorkspaceUploadedFile(
        file_id=file_id,
        workspace_id=workspace_id,
        relative_path=relative_path,
        filename=safe_name,
        content_type=content_type.strip() or "application/octet-stream",
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        created_at=datetime.now(tz=UTC),
    )
