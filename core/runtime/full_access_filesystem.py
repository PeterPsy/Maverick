"""Direct host filesystem primitives for explicitly authorized full access."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from core.egress.classification import fail_closed_classification
from core.runtime.confined_filesystem import (
    ConfinedFilesystemResult,
    FilesystemResourceObservation,
)
from core.runtime.full_access_filesystem_mutations import (
    FullAccessFilesystemMutationMixin,
)
from core.runtime.full_access_filesystem_support import (
    cursor,
    cursor_offset,
    decode_utf8,
    digest_json,
    file_digest,
    file_type,
    require_expected,
    stat_revision,
)
from core.runtime.runtime_paths import RuntimePathResolver
from core.runtime.tool_errors import RuntimeToolError


class FullAccessFilesystem(FullAccessFilesystemMutationMixin):
    """Filesystem facade that follows the full-access runtime boundary."""

    def __init__(self, *, workspace_id, workspace_root, classification_resolver=None):
        self.workspace_id = workspace_id
        self.workspace_root = Path(workspace_root)
        self.path_resolver = RuntimePathResolver(
            workspace_id=workspace_id,
            workspace_root=self.workspace_root,
            execution_mode="full-access",
        )
        self.classification_resolver = classification_resolver

    def path(self, value, *, allow_root=False) -> Path:
        return self.path_resolver.resolve(value, allow_root=allow_root).absolute

    def path_is_directory(self, value) -> bool:
        path = self.path(value, allow_root=True)
        if not path.exists() and not path.is_symlink():
            raise RuntimeToolError("filesystem_path_not_found")
        if path.is_symlink():
            return False
        return path.is_dir()

    def list_entries(self, value=".", *, max_depth, page_size, cursor=None):
        path = self.path(value, allow_root=True)
        if not path.is_dir():
            reason = (
                "filesystem_path_not_found"
                if not path.exists()
                else "filesystem_path_not_directory"
            )
            raise RuntimeToolError(reason)
        entries = self._walk(path, max_depth=max_depth)
        snapshot = digest_json(entries)
        offset = cursor_offset(cursor, expected_digest=snapshot)
        page = entries[offset : offset + page_size]
        next_offset = offset + len(page)
        observation = self._observation(path, "filesystem_listing", digest=snapshot)
        payload = {
            "path": str(path),
            "entries": page,
            "result_count": len(page),
            "total_result_count": len(entries),
            "truncated": next_offset < len(entries),
            "next_cursor": (
                cursor(next_offset, snapshot) if next_offset < len(entries) else None
            ),
            "snapshot_id": snapshot,
            "resource_identity": observation.resource_identity,
            "resource_revision": observation.resource_revision,
            "resource_digest": observation.resource_digest,
            "excluded_names": (),
        }
        return ConfinedFilesystemResult(payload, self._classification(observation))

    def search_text(
        self,
        value,
        *,
        query,
        max_depth,
        page_size,
        cursor=None,
        case_sensitive=True,
    ):
        if not isinstance(query, str) or not query:
            raise RuntimeToolError("tool_arguments_invalid")
        path = self.path(value, allow_root=True)
        if not path.is_dir():
            reason = (
                "filesystem_path_not_found"
                if not path.exists()
                else "filesystem_path_not_directory"
            )
            raise RuntimeToolError(reason)
        needle = query if case_sensitive else query.casefold()
        matches: list[dict[str, object]] = []
        for entry in self._walk(path, max_depth=max_depth):
            if entry["type"] != "file":
                continue
            candidate = Path(str(entry["path"]))
            try:
                content = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                if needle in (line if case_sensitive else line.casefold()):
                    matches.append(
                        {
                            "path": str(candidate),
                            "line": line_number,
                            "text": line,
                        }
                    )
        snapshot = digest_json(matches)
        offset = cursor_offset(cursor, expected_digest=snapshot)
        page = matches[offset : offset + page_size]
        next_offset = offset + len(page)
        observation = self._observation(path, "filesystem_search", digest=snapshot)
        payload = {
            "path": str(path),
            "query": query,
            "matches": page,
            "result_count": len(page),
            "total_result_count": len(matches),
            "truncated": next_offset < len(matches),
            "next_cursor": (
                cursor(next_offset, snapshot) if next_offset < len(matches) else None
            ),
            "snapshot_id": snapshot,
            "resource_identity": observation.resource_identity,
            "resource_revision": observation.resource_revision,
            "resource_digest": observation.resource_digest,
        }
        return ConfinedFilesystemResult(payload, self._classification(observation))

    def read_text(self, value, **arguments):
        return self._read(value, binary=False, **arguments)

    def read_bytes(self, value, **arguments):
        return self._read(value, binary=True, **arguments)

    def _read(self, value, *, binary, offset=0, max_bytes, **expected):
        path = self.path(value)
        if not path.is_file():
            raise RuntimeToolError(
                "filesystem_path_not_found" if not path.exists() else "filesystem_path_not_file"
            )
        observation = self._observation(path, "filesystem_file")
        require_expected(
            observation,
            expected.get("expected_resource_identity"),
            expected.get("expected_resource_revision"),
            expected.get("expected_resource_digest"),
        )
        try:
            with path.open("rb") as handle:
                handle.seek(offset)
                raw = handle.read(max_bytes)
            size = path.stat().st_size
        except OSError as error:
            raise RuntimeToolError("filesystem_read_failed") from error
        next_offset = offset + len(raw)
        payload = {
            "path": str(path),
            ("content_base64" if binary else "content"): (
                base64.b64encode(raw).decode("ascii")
                if binary
                else decode_utf8(raw)
            ),
            "byte_count": len(raw),
            "offset": offset,
            "next_offset": next_offset if next_offset < size else None,
            "truncated": next_offset < size,
            "resource_identity": observation.resource_identity,
            "resource_revision": observation.resource_revision,
            "resource_digest": observation.resource_digest,
        }
        if binary:
            payload["encoding"] = "base64"
        return ConfinedFilesystemResult(payload, self._classification(observation))

    def _walk(self, root, *, max_depth):
        entries: list[dict[str, object]] = []
        for current, directories, files in os.walk(root):
            current_path = Path(current)
            depth = len(current_path.relative_to(root).parts)
            directory_names = tuple(directories)
            if depth + 1 >= max_depth:
                directories[:] = []
            for name in sorted((*directory_names, *files)):
                path = current_path / name
                try:
                    info = path.lstat()
                except OSError:
                    continue
                kind = file_type(info.st_mode)
                entries.append(
                    {
                        "path": str(path),
                        "name": name,
                        "type": kind,
                        "depth": depth + 1,
                        "size_bytes": (
                            info.st_size if kind == "file" else None
                        ),
                    }
                )
        return sorted(
            entries,
            key=lambda item: (int(item["depth"]), str(item["path"])),
        )

    def _observation(self, path, kind, *, digest=None):
        try:
            info = path.lstat() if kind == "filesystem_path" else path.stat()
        except OSError as error:
            raise RuntimeToolError("filesystem_path_not_found") from error
        revision = stat_revision(info)
        return FilesystemResourceObservation(
            workspace_id=self.workspace_id,
            resource_kind=kind,
            resource_ref=str(path),
            resource_identity=f"{info.st_dev}:{info.st_ino}",
            resource_revision=digest or revision,
            resource_digest=(
                digest
                or (
                    file_digest(path)
                    if kind == "filesystem_file" and path.is_file()
                    else revision
                )
            ),
        )

    def _classification(self, observation):
        if self.classification_resolver is not None:
            try:
                return self.classification_resolver(observation, "tool_result")
            except Exception:
                pass
        return fail_closed_classification(
            provenance="tool_result",
            source_ref=observation.resource_ref,
            source_revision=observation.resource_revision,
            source_digest=observation.resource_digest,
            resource_identity=observation.resource_identity,
        )


__all__ = ["FullAccessFilesystem"]
