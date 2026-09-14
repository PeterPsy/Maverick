"""Canonical path resolution shared by hosted runtime tools."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from core.runtime.tool_errors import RuntimeToolError


@dataclass(frozen=True)
class ResolvedRuntimePath:
    """One unambiguous runtime path in host and workspace notation."""

    absolute: Path
    workspace_relative: str | None

    def for_confined_filesystem(self) -> str:
        if self.workspace_relative is None:
            raise RuntimeToolError("filesystem_path_outside_workspace")
        return self.workspace_relative


class RuntimePathResolver:
    """Resolve relative, workspace URI, and policy-allowed absolute paths."""

    def __init__(
        self,
        *,
        workspace_id: str,
        workspace_root: Path,
        execution_mode: str,
    ) -> None:
        root = Path(os.path.abspath(os.fspath(workspace_root)))
        if not workspace_id or not root.is_absolute():
            raise RuntimeToolError("filesystem_configuration_invalid")
        if execution_mode not in {"sandbox", "full-access"}:
            raise RuntimeToolError("tool_execution_mode_mismatch")
        self.workspace_id = workspace_id
        self.workspace_root = root
        self.execution_mode = execution_mode

    def resolve(self, value: object, *, allow_root: bool = False) -> ResolvedRuntimePath:
        raw = self._path_string(value)
        workspace_uri = raw.startswith("workspace://")
        if workspace_uri:
            candidate = self._workspace_uri_path(raw)
        else:
            path = Path(raw)
            candidate = path if path.is_absolute() else self.workspace_root / path
        absolute = Path(os.path.abspath(os.fspath(candidate)))
        workspace_relative = self._workspace_relative(absolute)
        if self.execution_mode != "full-access" and workspace_relative is None:
            raise RuntimeToolError("filesystem_path_outside_workspace")
        if workspace_uri and workspace_relative is None:
            raise RuntimeToolError("filesystem_path_outside_workspace")
        if not allow_root and absolute == Path(absolute.anchor):
            raise RuntimeToolError("filesystem_path_invalid")
        if not allow_root and workspace_relative == ".":
            raise RuntimeToolError("filesystem_path_invalid")
        return ResolvedRuntimePath(absolute, workspace_relative)

    def _workspace_uri_path(self, raw: str) -> Path:
        try:
            parsed = urlsplit(raw)
            parsed_port = parsed.port
        except ValueError as error:
            raise RuntimeToolError("filesystem_workspace_uri_invalid") from error
        if (
            parsed.scheme != "workspace"
            or parsed.netloc != self.workspace_id
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
            or parsed_port is not None
        ):
            raise RuntimeToolError("filesystem_workspace_uri_invalid")
        decoded = unquote(parsed.path)
        if "%" in decoded or "\x00" in decoded:
            raise RuntimeToolError("filesystem_workspace_uri_invalid")
        relative = decoded.lstrip("/") or "."
        posix = PurePosixPath(relative)
        if posix.is_absolute() or any(part in {"", ".."} for part in posix.parts):
            raise RuntimeToolError("filesystem_workspace_uri_invalid")
        return self.workspace_root / posix.as_posix()

    def _workspace_relative(self, absolute: Path) -> str | None:
        try:
            relative = absolute.relative_to(self.workspace_root)
        except ValueError:
            return None
        return relative.as_posix() or "."

    @staticmethod
    def _path_string(value: object) -> str:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise RuntimeToolError("filesystem_path_invalid")
        return value


__all__ = ["ResolvedRuntimePath", "RuntimePathResolver"]
