"""Direct host filesystem primitives for explicitly authorized full access."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from core.egress.classification import (
    derive_content_classification,
    fail_closed_classification,
)
from core.runtime.confined_filesystem import (
    ConfinedFilesystemResult,
    FilesystemResourceObservation,
)
from core.runtime.full_access_filesystem_mutations import (
    FullAccessFilesystemMutationMixin,
)
from core.runtime.full_access_filesystem_scanner import FullAccessFilesystemScanner
from core.runtime.full_access_filesystem_support import (
    cursor as encode_cursor,
    cursor_state,
    decode_utf8,
    file_digest,
    require_expected,
    stat_revision,
)
from core.runtime.runtime_paths import RuntimePathResolver
from core.runtime.tool_errors import RuntimeToolError


class FullAccessFilesystem(FullAccessFilesystemMutationMixin):
    """Filesystem facade that follows the full-access runtime boundary."""

    def __init__(
        self,
        *,
        workspace_id,
        workspace_root,
        classification_resolver=None,
        max_scan_entries: int = 50_000,
        max_search_bytes: int = 64 * 1024 * 1024,
        max_search_file_bytes: int = 2 * 1024 * 1024,
    ):
        if min(max_scan_entries, max_search_bytes, max_search_file_bytes) <= 0:
            raise ValueError("Full-access filesystem scan limits must be positive.")
        self.workspace_id = workspace_id
        self.workspace_root = Path(workspace_root)
        self.path_resolver = RuntimePathResolver(
            workspace_id=workspace_id,
            workspace_root=self.workspace_root,
            execution_mode="full-access",
        )
        self.classification_resolver = classification_resolver
        self.max_scan_entries = max_scan_entries
        self.max_search_bytes = max_search_bytes
        self.max_search_file_bytes = max_search_file_bytes

    def path(self, value, *, allow_root=False) -> Path:
        return self.path_resolver.resolve(value, allow_root=allow_root).absolute

    def path_is_directory(self, value) -> bool:
        path = self.path(value, allow_root=True)
        if not path.exists() and not path.is_symlink():
            raise RuntimeToolError("filesystem_path_not_found")
        if path.is_symlink():
            return False
        return path.is_dir()

    def list_entries(
        self,
        value=".",
        *,
        max_depth,
        page_size,
        cursor=None,
        execution_control=None,
    ):
        path = self.path(value, allow_root=True)
        if not path.is_dir():
            reason = (
                "filesystem_path_not_found"
                if not path.exists()
                else "filesystem_path_not_directory"
            )
            raise RuntimeToolError(reason)
        offset, expected_snapshot = cursor_state(cursor)
        scanner = FullAccessFilesystemScanner(self.max_scan_entries)
        digest = _JsonArrayDigest()
        page: list[dict[str, object]] = []
        entry_paths: list[Path] = []
        total_count = 0
        for entry, entry_path in scanner.walk(
            path,
            max_depth=max_depth,
            execution_control=execution_control,
        ):
            digest.add(entry)
            if offset <= total_count < offset + page_size:
                page.append(entry)
                entry_paths.append(entry_path)
            total_count += 1
        snapshot = digest.finish()
        if expected_snapshot is not None and expected_snapshot != snapshot:
            raise RuntimeToolError("filesystem_cursor_invalid")
        next_offset = offset + len(page)
        observation = self._observation(path, "filesystem_listing", digest=snapshot)
        payload = {
            "path": str(path),
            "entries": page,
            "result_count": len(page),
            "total_result_count": total_count,
            "truncated": next_offset < total_count or scanner.truncated,
            "next_cursor": (
                encode_cursor(next_offset, snapshot)
                if next_offset < total_count
                else None
            ),
            "scan_truncated": scanner.truncated,
            "scan_entry_limit": self.max_scan_entries,
            "snapshot_id": snapshot,
            "resource_identity": observation.resource_identity,
            "resource_revision": observation.resource_revision,
            "resource_digest": observation.resource_digest,
            "excluded_names": (),
        }
        return ConfinedFilesystemResult(
            payload,
            self._aggregate_classification(observation, payload, entry_paths),
        )

    def search_text(
        self,
        value,
        *,
        query,
        max_depth,
        page_size,
        cursor=None,
        case_sensitive=True,
        execution_control=None,
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
        offset, expected_snapshot = cursor_state(cursor)
        scanner = FullAccessFilesystemScanner(self.max_scan_entries)
        digest = _JsonArrayDigest()
        page: list[dict[str, object]] = []
        page_paths: list[Path] = []
        total_count = 0
        scanned_bytes = 0
        truncated_file_count = 0
        search_truncated = False
        for entry, candidate in scanner.walk(
            path,
            max_depth=max_depth,
            execution_control=execution_control,
        ):
            if entry["type"] != "file":
                continue
            self._check_execution(execution_control)
            remaining = self.max_search_bytes - scanned_bytes
            if remaining <= 0:
                search_truncated = True
                break
            read_limit = min(self.max_search_file_bytes, remaining)
            try:
                with candidate.open("rb") as handle:
                    raw = handle.read(read_limit)
                size_bytes = candidate.stat().st_size
            except OSError:
                continue
            scanned_bytes += len(raw)
            self._check_execution(execution_control)
            if size_bytes > len(raw):
                truncated_file_count += 1
                if read_limit == remaining:
                    search_truncated = True
            try:
                content = _decode_utf8_prefix(raw, truncated=size_bytes > len(raw))
            except UnicodeError:
                if search_truncated:
                    break
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                self._check_execution(execution_control)
                if needle in (line if case_sensitive else line.casefold()):
                    match = {
                        "path": str(candidate),
                        "line": line_number,
                        "text": line[:2048],
                        "text_truncated": len(line) > 2048,
                    }
                    digest.add(match)
                    if offset <= total_count < offset + page_size:
                        page.append(match)
                        page_paths.append(candidate)
                    total_count += 1
            if search_truncated:
                break
        snapshot = digest.finish()
        if expected_snapshot is not None and expected_snapshot != snapshot:
            raise RuntimeToolError("filesystem_cursor_invalid")
        next_offset = offset + len(page)
        observation = self._observation(path, "filesystem_search", digest=snapshot)
        payload = {
            "path": str(path),
            "query": query,
            "matches": page,
            "result_count": len(page),
            "total_result_count": total_count,
            "truncated": next_offset < total_count or scanner.truncated,
            "next_cursor": (
                encode_cursor(next_offset, snapshot)
                if next_offset < total_count
                else None
            ),
            "scan_truncated": (
                scanner.truncated or search_truncated or truncated_file_count > 0
            ),
            "scan_entry_limit": self.max_scan_entries,
            "scanned_bytes": scanned_bytes,
            "scan_byte_limit": self.max_search_bytes,
            "truncated_file_count": truncated_file_count,
            "per_file_byte_limit": self.max_search_file_bytes,
            "snapshot_id": snapshot,
            "resource_identity": observation.resource_identity,
            "resource_revision": observation.resource_revision,
            "resource_digest": observation.resource_digest,
        }
        return ConfinedFilesystemResult(
            payload,
            self._aggregate_classification(observation, payload, page_paths),
        )

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

    @staticmethod
    def _check_execution(execution_control) -> None:
        if execution_control is not None:
            execution_control.check()

    def _aggregate_classification(self, observation, payload, paths):
        sources = [self._classification(observation)]
        for path in dict.fromkeys(paths):
            try:
                sources.append(
                    self._classification(
                        self._observation(path, "filesystem_path")
                    )
                )
            except RuntimeToolError:
                sources.append(
                    fail_closed_classification(
                        provenance="tool_result",
                        source_ref=str(path),
                    )
                )
        content = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return derive_content_classification(
            content=content,
            provenance="tool_result",
            source_ref=f"full-access-filesystem:{observation.resource_ref}",
            sources=sources,
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


class _JsonArrayDigest:
    """Compute the canonical digest of a JSON array without retaining it."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self._digest.update(b"[")
        self._count = 0

    def add(self, value: dict[str, object]) -> None:
        if self._count:
            self._digest.update(b",")
        self._digest.update(
            json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        self._count += 1

    def finish(self) -> str:
        digest = self._digest.copy()
        digest.update(b"]")
        return digest.hexdigest()


def _decode_utf8_prefix(value: bytes, *, truncated: bool) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as error:
        if truncated and error.end == len(value) and len(value) - error.start <= 4:
            return value[: error.start].decode("utf-8")
        raise
