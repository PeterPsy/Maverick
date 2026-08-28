"""Descriptor-backed resolution of workspace ``AGENTS.md`` instructions."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

from core.egress.classification import CanonicalSourceClassification
from core.runtime.confined_filesystem import (
    ConfinedFilesystemResult,
    ConfinedWorkspaceFilesystem,
)
from core.runtime.tool_errors import RuntimeToolError


MAX_INSTRUCTION_FILE_BYTES = 1_048_576
INSTRUCTION_READ_CHUNK_BYTES = 262_144


@dataclass(frozen=True)
class ResolvedWorkspaceInstruction:
    """One applicable instruction file and the scope it governs."""

    relative_path: str
    scope_path: str
    content: str
    resource_identity: str
    resource_revision: str
    resource_digest: str
    classification: CanonicalSourceClassification


def resolve_workspace_instruction_chain(
    filesystem: ConfinedWorkspaceFilesystem,
    *,
    workspace_root: Path,
    workdir: str | Path,
) -> tuple[ResolvedWorkspaceInstruction, ...]:
    """Resolve root-to-leaf ``AGENTS.md`` files for one verified workdir."""
    relative_workdir = workspace_relative_workdir(
        workspace_root=workspace_root,
        workdir=workdir,
    )
    with filesystem.open_shell_cwd(relative_workdir):
        pass
    parts = () if relative_workdir == "." else PurePosixPath(relative_workdir).parts
    scopes = [PurePosixPath(".")]
    current = PurePosixPath(".")
    for part in parts:
        current /= part
        scopes.append(current)

    resolved: list[ResolvedWorkspaceInstruction] = []
    for scope in scopes:
        relative_path = (
            "AGENTS.md" if str(scope) == "." else f"{scope.as_posix()}/AGENTS.md"
        )
        candidate = workspace_root / relative_path
        if not os.path.lexists(candidate):
            continue
        result = read_complete_confined_text(
            filesystem,
            relative_path,
            max_bytes=MAX_INSTRUCTION_FILE_BYTES,
        )
        payload = result.payload
        resolved.append(
            ResolvedWorkspaceInstruction(
                relative_path=relative_path,
                scope_path=scope.as_posix(),
                content=str(payload["content"]),
                resource_identity=str(payload["resource_identity"]),
                resource_revision=str(payload["resource_revision"]),
                resource_digest=str(payload["resource_digest"]),
                classification=result.classification,
            )
        )
    return tuple(resolved)


def workspace_relative_workdir(
    *,
    workspace_root: Path,
    workdir: str | Path,
) -> str:
    """Return a normalized relative workdir or reject an escape."""
    root = Path(os.path.abspath(os.fspath(workspace_root)))
    candidate = Path(workdir)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.abspath(os.fspath(candidate)))
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise RuntimeToolError("workspace_instruction_scope_outside_workspace") from error
    if any(part in {"", ".", "..", ".git"} for part in relative.parts):
        raise RuntimeToolError("workspace_instruction_scope_invalid")
    return relative.as_posix() or "."


def resolve_workspace_instruction_chain_for_path(
    filesystem: ConfinedWorkspaceFilesystem,
    *,
    workspace_root: Path,
    relative_path: str,
    target_is_directory: bool = False,
) -> tuple[ResolvedWorkspaceInstruction, ...]:
    """Resolve instructions through the deepest existing parent of one target."""
    components = filesystem._components(relative_path, allow_root=True)
    scope_components = components if target_is_directory else components[:-1]
    while True:
        scope = "/".join(scope_components) or "."
        try:
            with filesystem.open_shell_cwd(scope):
                pass
            break
        except RuntimeToolError as error:
            if error.reason_code != "filesystem_path_not_found" or not scope_components:
                raise
            scope_components = scope_components[:-1]
    return resolve_workspace_instruction_chain(
        filesystem,
        workspace_root=workspace_root,
        workdir=workspace_root / scope,
    )


def workspace_instruction_scope_digest(
    instructions: tuple[ResolvedWorkspaceInstruction, ...],
) -> str:
    """Digest the complete applicable instruction scope without host paths."""
    return hashlib.sha256(
        json.dumps(
            [
                {
                    "path": item.relative_path,
                    "scope": item.scope_path,
                    "resource_identity": item.resource_identity,
                    "resource_revision": item.resource_revision,
                    "resource_digest": item.resource_digest,
                    "content_digest": hashlib.sha256(
                        item.content.encode("utf-8")
                    ).hexdigest(),
                }
                for item in instructions
            ],
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def read_complete_confined_text(
    filesystem: ConfinedWorkspaceFilesystem,
    relative_path: str,
    *,
    max_bytes: int,
) -> ConfinedFilesystemResult:
    """Read a complete bounded UTF-8 file while fencing every continuation."""
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise RuntimeToolError("tool_arguments_invalid")
    chunks: list[str] = []
    offset = 0
    identity: str | None = None
    revision: str | None = None
    first: ConfinedFilesystemResult | None = None
    while True:
        remaining = max_bytes - offset
        if remaining < 1:
            raise RuntimeToolError("workspace_instruction_too_large")
        result = filesystem.read_text(
            relative_path,
            offset=offset,
            max_bytes=min(INSTRUCTION_READ_CHUNK_BYTES, remaining),
            expected_resource_identity=identity,
            expected_resource_revision=revision,
        )
        if first is None:
            first = result
            identity = str(result.payload["resource_identity"])
            revision = str(result.payload["resource_revision"])
        elif (
            result.payload.get("resource_identity") != identity
            or result.payload.get("resource_revision") != revision
        ):
            raise RuntimeToolError("filesystem_resource_changed")
        chunks.append(str(result.payload["content"]))
        next_offset = result.payload.get("next_offset")
        if next_offset is None:
            break
        if not isinstance(next_offset, int) or next_offset <= offset:
            raise RuntimeToolError("filesystem_chunk_offset_invalid")
        offset = next_offset
    assert first is not None
    payload = dict(first.payload)
    content = "".join(chunks)
    payload.update(
        {
            "content": content,
            "byte_count": len(content.encode("utf-8")),
            "offset": 0,
            "next_offset": None,
            "truncated": False,
        }
    )
    return ConfinedFilesystemResult(payload, first.classification)


__all__ = [
    "MAX_INSTRUCTION_FILE_BYTES",
    "ResolvedWorkspaceInstruction",
    "read_complete_confined_text",
    "resolve_workspace_instruction_chain",
    "resolve_workspace_instruction_chain_for_path",
    "workspace_instruction_scope_digest",
    "workspace_relative_workdir",
]
