"""Linux descriptor-relative workspace filesystem primitives.

Every component is opened relative to an already-open directory descriptor.
Path strings are used only to select components; an opened resource is never
closed and reopened by pathname before use.  Post-use link and version checks
discard results when a rename, swap, or mutation races the operation.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
from typing import Callable, Protocol

from core.egress.classification import (
    CanonicalSourceClassification,
    fail_closed_classification,
    join_classifications,
)
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.confined_filesystem_metadata import (
    ConfinedPathMetadata,
    capture_fd_metadata,
)
from core.runtime.confined_filesystem_mutation_support import (
    rename_exchange,
    rename_noreplace,
    same_identity,
)


MAX_CONFINED_LIST_ENTRIES = 10_000
MAX_CONFINED_PATH_COMPONENTS = 256
_CURSOR_DOMAIN = b"maverick.confined-filesystem.cursor.v1\x00"
_PROCESS_CURSOR_KEY = secrets.token_bytes(32)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_NOATIME = getattr(os, "O_NOATIME", 0)


@dataclass(frozen=True)
class FilesystemResourceObservation:
    """Identity/version of the resource actually consumed through a descriptor."""

    workspace_id: str
    resource_kind: str
    resource_ref: str
    resource_identity: str
    resource_revision: str
    resource_digest: str


@dataclass(frozen=True)
class ConfinedFilesystemResult:
    payload: dict[str, object]
    classification: CanonicalSourceClassification


ResourceClassificationResolver = Callable[
    [FilesystemResourceObservation, str], CanonicalSourceClassification
]
FilesystemRaceHook = Callable[[str, str], None]


class FilesystemMutationGuard(Protocol):
    def verify_before(self) -> None: ...

    def verify_after(self) -> None: ...


@dataclass
class _DirectoryAnchor:
    parent_fd: int | None
    fd: int
    name: str | None
    relative_path: str
    opened_stat: os.stat_result


@dataclass(frozen=True)
class _EntryAnchor:
    parent_fd: int
    name: str
    opened_stat: os.stat_result


class _OpenChain:
    def __init__(self, anchors: list[_DirectoryAnchor]) -> None:
        self.anchors = anchors

    @property
    def leaf_fd(self) -> int:
        return self.anchors[-1].fd

    def close(self) -> None:
        for anchor in reversed(self.anchors):
            try:
                os.close(anchor.fd)
            except OSError:
                pass

    def __enter__(self) -> "_OpenChain":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class ConfinedWorkspaceFilesystem:
    """Bounded read/list/write methods anchored to one verified workspace root."""

    def __init__(
        self,
        *,
        workspace_id: str,
        workspace_root: Path,
        classification_resolver: ResourceClassificationResolver | None = None,
        cursor_key: bytes | None = None,
        race_hook: FilesystemRaceHook | None = None,
    ) -> None:
        if not _NOFOLLOW or not _DIRECTORY:
            raise RuntimeToolError("filesystem_nofollow_unavailable")
        root = Path(os.path.abspath(os.fspath(workspace_root)))
        if not root.is_absolute() or ".." in root.parts:
            raise RuntimeToolError("filesystem_root_invalid")
        self.workspace_id = str(workspace_id or "")
        self.workspace_root = root
        self.classification_resolver = classification_resolver
        self.cursor_key = bytes(cursor_key or _PROCESS_CURSOR_KEY)
        self.race_hook = race_hook
        self._root_fd = -1
        self._root_stat: os.stat_result | None = None
        if not self.workspace_id or len(self.cursor_key) < 32:
            raise RuntimeToolError("filesystem_configuration_invalid")
        self._root_fd = self._open_configured_root()
        self._root_stat = os.fstat(self._root_fd)
        try:
            self._assert_root_location(self._root_fd)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Release the pinned root descriptor without ever reopening its path."""
        if self._root_fd >= 0:
            try:
                os.close(self._root_fd)
            except OSError:
                pass
            self._root_fd = -1

    def __del__(self) -> None:
        self.close()

    def read_text(
        self,
        relative_path: str,
        *,
        offset: int = 0,
        max_bytes: int,
        expected_resource_identity: str | None = None,
        expected_resource_revision: str | None = None,
    ) -> ConfinedFilesystemResult:
        """Read one UTF-8 chunk and reject cross-call or in-call mutations."""
        components = self._components(relative_path, allow_root=False)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise RuntimeToolError("tool_arguments_invalid")
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
            raise RuntimeToolError("tool_arguments_invalid")
        if offset and (not expected_resource_identity or not expected_resource_revision):
            raise RuntimeToolError("filesystem_chunk_identity_required")
        with self._open_chain(components[:-1]) as chain:
            self._hook("read_parent_opened", relative_path)
            fd = self._open_file(chain.leaf_fd, components[-1], write=False)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode):
                    raise RuntimeToolError("filesystem_path_not_file")
                observation = self._observation(
                    "filesystem_file", self._relative(components), before
                )
                self._require_expected(
                    observation,
                    identity=expected_resource_identity,
                    revision=expected_resource_revision,
                )
                if offset > before.st_size:
                    raise RuntimeToolError("filesystem_chunk_offset_invalid")
                self._hook("read_file_opened", relative_path)
                raw = os.pread(fd, min(max_bytes, max(0, before.st_size - offset)), offset)
                valid = _utf8_prefix(raw)
                if raw and not valid:
                    raise RuntimeToolError("filesystem_utf8_chunk_too_small")
                after = os.fstat(fd)
                self._assert_same_version(before, after, "filesystem_resource_changed")
                self._assert_final_link(chain.leaf_fd, components[-1], after)
                self._assert_chain(chain)
                next_offset = offset + len(valid)
                payload = {
                    "path": observation.resource_ref,
                    "content": valid.decode("utf-8"),
                    "byte_count": len(valid),
                    "offset": offset,
                    "next_offset": next_offset if next_offset < after.st_size else None,
                    "truncated": next_offset < after.st_size,
                    "resource_identity": observation.resource_identity,
                    "resource_revision": observation.resource_revision,
                    "resource_digest": observation.resource_digest,
                }
                return ConfinedFilesystemResult(
                    payload,
                    self._classification(observation, "tool_result"),
                )
            except OSError as error:
                raise RuntimeToolError("filesystem_read_failed") from error
            finally:
                os.close(fd)

    def read_bytes(
        self,
        relative_path: str,
        *,
        offset: int = 0,
        max_bytes: int,
        expected_resource_identity: str | None = None,
        expected_resource_revision: str | None = None,
    ) -> ConfinedFilesystemResult:
        """Read one raw byte chunk as base64 with the same version fencing."""
        components = self._components(relative_path, allow_root=False)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise RuntimeToolError("tool_arguments_invalid")
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
            raise RuntimeToolError("tool_arguments_invalid")
        if offset and (not expected_resource_identity or not expected_resource_revision):
            raise RuntimeToolError("filesystem_chunk_identity_required")
        with self._open_chain(components[:-1]) as chain:
            self._hook("read_parent_opened", relative_path)
            fd = self._open_file(chain.leaf_fd, components[-1], write=False)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode):
                    raise RuntimeToolError("filesystem_path_not_file")
                observation = self._observation(
                    "filesystem_file", self._relative(components), before
                )
                self._require_expected(
                    observation,
                    identity=expected_resource_identity,
                    revision=expected_resource_revision,
                )
                if offset > before.st_size:
                    raise RuntimeToolError("filesystem_chunk_offset_invalid")
                self._hook("read_file_opened", relative_path)
                raw = os.pread(
                    fd,
                    min(max_bytes, max(0, before.st_size - offset)),
                    offset,
                )
                after = os.fstat(fd)
                self._assert_same_version(before, after, "filesystem_resource_changed")
                self._assert_final_link(chain.leaf_fd, components[-1], after)
                self._assert_chain(chain)
                next_offset = offset + len(raw)
                payload = {
                    "path": observation.resource_ref,
                    "content_base64": base64.b64encode(raw).decode("ascii"),
                    "encoding": "base64",
                    "byte_count": len(raw),
                    "offset": offset,
                    "next_offset": next_offset if next_offset < after.st_size else None,
                    "truncated": next_offset < after.st_size,
                    "resource_identity": observation.resource_identity,
                    "resource_revision": observation.resource_revision,
                    "resource_digest": observation.resource_digest,
                }
                return ConfinedFilesystemResult(
                    payload,
                    self._classification(observation, "tool_result"),
                )
            except OSError as error:
                raise RuntimeToolError("filesystem_read_failed") from error
            finally:
                os.close(fd)

    def read_file_bytes_for_validation(
        self,
        relative_path: str,
        *,
        max_bytes: int,
        expected_resource_identity: str,
        expected_resource_revision: str,
    ) -> bytes | None:
        """Read exact validation bytes without changing the source atime."""
        if not _NOATIME:
            raise RuntimeToolError("filesystem_noatime_unavailable")
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
            raise RuntimeToolError("tool_arguments_invalid")
        components = self._components(relative_path, allow_root=False)
        with self._open_chain(components[:-1]) as chain:
            try:
                fd = os.open(
                    components[-1],
                    os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _NOATIME,
                    dir_fd=chain.leaf_fd,
                )
            except OSError as error:
                raise RuntimeToolError("filesystem_metadata_unavailable") from error
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode):
                    raise RuntimeToolError("filesystem_path_not_file")
                observation = self._observation(
                    "filesystem_file",
                    self._relative(components),
                    before,
                )
                self._require_expected(
                    observation,
                    identity=expected_resource_identity,
                    revision=expected_resource_revision,
                )
                if before.st_size > max_bytes:
                    content = None
                else:
                    content = os.pread(fd, before.st_size + 1, 0)
                    if len(content) != before.st_size:
                        raise RuntimeToolError("filesystem_resource_changed")
                after = os.fstat(fd)
                self._assert_same_version(
                    before,
                    after,
                    "filesystem_resource_changed",
                )
                self._assert_final_link(chain.leaf_fd, components[-1], after)
                self._assert_chain(chain)
                return content
            finally:
                os.close(fd)

    def observe_file(
        self,
        relative_path: str,
        *,
        provenance: str,
    ) -> tuple[FilesystemResourceObservation, CanonicalSourceClassification]:
        """Classify the exact file identity referenced by an input block."""
        components = self._components(relative_path, allow_root=False)
        with self._open_chain(components[:-1]) as chain:
            fd = self._open_file(chain.leaf_fd, components[-1], write=False)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode):
                    raise RuntimeToolError("filesystem_path_not_file")
                self._hook("observe_file_opened", relative_path)
                after = os.fstat(fd)
                self._assert_same_version(
                    before,
                    after,
                    "filesystem_resource_changed",
                )
                self._assert_final_link(chain.leaf_fd, components[-1], after)
                self._assert_chain(chain)
                observation = self._observation(
                    "filesystem_file",
                    self._relative(components),
                    after,
                )
                return observation, self._classification(observation, provenance)
            finally:
                os.close(fd)

    def list_entries(
        self,
        relative_path: str = ".",
        *,
        max_depth: int,
        page_size: int,
        cursor: str | None = None,
    ) -> ConfinedFilesystemResult:
        """Return a stable page; every later page revalidates the full snapshot."""
        if not isinstance(max_depth, int) or isinstance(max_depth, bool) or max_depth < 1:
            raise RuntimeToolError("tool_arguments_invalid")
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            raise RuntimeToolError("tool_arguments_invalid")
        cursor_data = self._decode_cursor(cursor) if cursor else None
        if cursor_data is not None:
            relative_path = str(cursor_data["path"])
            max_depth = int(cursor_data["max_depth"])
            page_size = int(cursor_data["page_size"])
        components = self._components(relative_path, allow_root=True)
        with self._open_chain(components) as requested:
            requested_before = os.fstat(requested.leaf_fd)
            observation = self._observation(
                "filesystem_directory", self._relative(components), requested_before
            )
            entries, anchors, entry_anchors = self._scan_tree(
                requested.leaf_fd,
                base_components=components,
                max_depth=max_depth,
            )
            try:
                self._hook("list_scanned", relative_path)
                requested_after = os.fstat(requested.leaf_fd)
                self._assert_same_version(
                    requested_before,
                    requested_after,
                    "filesystem_snapshot_changed",
                )
                for anchor in anchors:
                    self._assert_anchor(anchor, version=True)
                for entry_anchor in entry_anchors:
                    self._assert_entry_snapshot(entry_anchor)
                self._assert_chain(requested)
                snapshot_id = _snapshot_digest(observation, entries, max_depth)
                listing_observation = FilesystemResourceObservation(
                    workspace_id=self.workspace_id,
                    resource_kind="filesystem_listing",
                    resource_ref=observation.resource_ref,
                    resource_identity=observation.resource_identity,
                    resource_revision=snapshot_id,
                    resource_digest=snapshot_id,
                )
                offset = 0
                if cursor_data is not None:
                    if (
                        cursor_data["snapshot_id"] != snapshot_id
                        or cursor_data["resource_identity"]
                        != listing_observation.resource_identity
                        or cursor_data["resource_revision"]
                        != listing_observation.resource_revision
                    ):
                        raise RuntimeToolError("filesystem_snapshot_changed")
                    offset = int(cursor_data["offset"])
                page = entries[offset : offset + page_size]
                next_offset = offset + len(page)
                next_cursor = None
                if next_offset < len(entries):
                    next_cursor = self._encode_cursor(
                        {
                            "v": 1,
                            "path": self._relative(components),
                            "max_depth": max_depth,
                            "page_size": page_size,
                            "snapshot_id": snapshot_id,
                            "resource_identity": listing_observation.resource_identity,
                            "resource_revision": listing_observation.resource_revision,
                            "offset": next_offset,
                        }
                    )
                payload = {
                    "path": listing_observation.resource_ref,
                    "entries": page,
                    "result_count": len(page),
                    "total_result_count": len(entries),
                    "truncated": next_cursor is not None,
                    "next_cursor": next_cursor,
                    "snapshot_id": snapshot_id,
                    "resource_identity": listing_observation.resource_identity,
                    "resource_revision": listing_observation.resource_revision,
                    "resource_digest": listing_observation.resource_digest,
                    "excluded_names": (".git", "runtime"),
                }
                return ConfinedFilesystemResult(
                    payload,
                    self._classification(listing_observation, "tool_result"),
                )
            finally:
                for anchor in reversed(anchors):
                    try:
                        os.close(anchor.fd)
                    except OSError:
                        pass

    def write_text(
        self,
        relative_path: str,
        *,
        content: str,
        create_only: bool,
        create_parents: bool = True,
        replace_only: bool = False,
        expected_resource_identity: str | None = None,
        expected_resource_revision: str | None = None,
        mutation_guard: FilesystemMutationGuard | None = None,
    ) -> ConfinedFilesystemResult:
        """Write and commit inside the verified parent descriptor only."""
        if not isinstance(content, str):
            raise RuntimeToolError("tool_arguments_invalid")
        if create_only and replace_only:
            raise RuntimeToolError("tool_arguments_invalid")
        if bool(expected_resource_identity) != bool(expected_resource_revision):
            raise RuntimeToolError("filesystem_expected_version_incomplete")
        components = self._components(relative_path, allow_root=False)
        chain = self._open_chain(components[:-1], create_missing=create_parents)
        temporary_name = f".maverick-write-{secrets.token_hex(16)}"
        temp_fd: int | None = None
        committed = False
        committed_stat: os.stat_result | None = None
        rollback_kind: str | None = None
        old_entry_retained = False
        preserve_temporary = False
        previous_stat: os.stat_result | None = None
        previous_observation: FilesystemResourceObservation | None = None
        try:
            parent_fd = chain.leaf_fd
            try:
                previous_stat = os.stat(
                    components[-1],
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                previous_stat = None
            if previous_stat is not None:
                if stat.S_ISLNK(previous_stat.st_mode):
                    raise RuntimeToolError("filesystem_symlink_denied")
                if not stat.S_ISREG(previous_stat.st_mode):
                    raise RuntimeToolError("filesystem_path_not_file")
                previous_observation = self._observation(
                    "filesystem_file",
                    self._relative(components),
                    previous_stat,
                )
            if replace_only and previous_stat is None:
                raise RuntimeToolError("filesystem_path_not_found")
            if expected_resource_identity is not None:
                if previous_observation is None:
                    raise RuntimeToolError("filesystem_resource_changed")
                self._require_expected(
                    previous_observation,
                    identity=expected_resource_identity,
                    revision=expected_resource_revision,
                )
            temp_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
                0o660,
                dir_fd=parent_fd,
            )
            payload = content.encode("utf-8")
            _write_all(temp_fd, payload)
            os.fsync(temp_fd)
            self._hook("write_temporary_ready", relative_path)
            if mutation_guard is not None:
                mutation_guard.verify_before()
            self._assert_chain(chain)
            if previous_stat is not None:
                try:
                    current_stat = os.stat(
                        components[-1],
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError as error:
                    raise RuntimeToolError("filesystem_resource_changed") from error
                self._assert_same_version(
                    previous_stat,
                    current_stat,
                    "filesystem_resource_changed",
                )
            elif not create_only:
                try:
                    os.stat(
                        components[-1],
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    pass
                else:
                    raise RuntimeToolError("filesystem_resource_changed")
            if create_only:
                try:
                    os.link(
                        temporary_name,
                        components[-1],
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError as error:
                    raise RuntimeToolError("filesystem_path_exists") from error
                os.unlink(temporary_name, dir_fd=parent_fd)
                rollback_kind = "created"
                committed = True
                committed_stat = os.fstat(temp_fd)
            elif previous_stat is not None:
                self._reject_existing_symlink(parent_fd, components[-1])
                rename_exchange(
                    parent_fd,
                    temporary_name,
                    parent_fd,
                    components[-1],
                )
                rollback_kind = "exchanged"
                old_entry_retained = True
                committed = True
                committed_stat = os.fstat(temp_fd)
                swapped = os.stat(
                    temporary_name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                if not same_identity(swapped, previous_stat) or not _same_exchange_version(
                    swapped,
                    previous_stat,
                ):
                    if not _rollback_confined_write(
                        parent_fd,
                        components[-1],
                        temporary_name,
                        committed_stat,
                        previous_stat=previous_stat,
                        rollback_kind=rollback_kind,
                        old_entry_retained=old_entry_retained,
                    ):
                        preserve_temporary = True
                        raise RuntimeToolError("tool_execution_unknown")
                    committed = False
                    old_entry_retained = False
                    raise RuntimeToolError("filesystem_resource_changed")
            else:
                rename_noreplace(
                    parent_fd,
                    temporary_name,
                    parent_fd,
                    components[-1],
                )
                rollback_kind = "created"
                committed = True
                committed_stat = os.fstat(temp_fd)
            os.fsync(parent_fd)
            self._hook("write_committed", relative_path)
            committed_after_hook = os.fstat(temp_fd)
            self._assert_same_version(
                committed_stat,
                committed_after_hook,
                "filesystem_resource_changed",
            )
            committed_stat = committed_after_hook
            self._assert_final_link(parent_fd, components[-1], committed_stat)
            self._assert_chain(chain)
            if mutation_guard is not None:
                mutation_guard.verify_after()
            observation = self._observation(
                "filesystem_file", self._relative(components), committed_stat
            )
            classification = self._classification(observation, "tool_result")
            if old_entry_retained:
                os.unlink(temporary_name, dir_fd=parent_fd)
                old_entry_retained = False
                os.fsync(parent_fd)
            return ConfinedFilesystemResult(
                {
                    "path": observation.resource_ref,
                    "byte_count": len(payload),
                    "created": previous_stat is None,
                    "replaced": previous_stat is not None,
                    "previous_resource_revision": (
                        None
                        if previous_observation is None
                        else previous_observation.resource_revision
                    ),
                    "previous_resource_digest": (
                        None
                        if previous_observation is None
                        else previous_observation.resource_digest
                    ),
                    "resource_identity": observation.resource_identity,
                    "resource_revision": observation.resource_revision,
                    "resource_digest": observation.resource_digest,
                },
                classification,
            )
        except RuntimeToolError as error:
            if committed and committed_stat is not None:
                if _rollback_confined_write(
                    chain.leaf_fd,
                    components[-1],
                    temporary_name,
                    committed_stat,
                    previous_stat=previous_stat,
                    rollback_kind=rollback_kind,
                    old_entry_retained=old_entry_retained,
                ):
                    committed = False
                else:
                    preserve_temporary = True
                    if error.reason_code != "tool_execution_unknown":
                        raise RuntimeToolError("tool_execution_unknown") from error
            raise
        except OSError as error:
            if committed and committed_stat is not None:
                if not _rollback_confined_write(
                    chain.leaf_fd,
                    components[-1],
                    temporary_name,
                    committed_stat,
                    previous_stat=previous_stat,
                    rollback_kind=rollback_kind,
                    old_entry_retained=old_entry_retained,
                ):
                    preserve_temporary = True
                    raise RuntimeToolError("tool_execution_unknown") from error
            raise RuntimeToolError("filesystem_write_failed") from error
        finally:
            if temp_fd is not None:
                os.close(temp_fd)
            if not preserve_temporary:
                try:
                    os.unlink(temporary_name, dir_fd=chain.leaf_fd)
                except OSError:
                    pass
            chain.close()

    def search_text(
        self,
        relative_path: str,
        *,
        query: str,
        max_depth: int,
        page_size: int,
        cursor: str | None = None,
        case_sensitive: bool = True,
    ) -> ConfinedFilesystemResult:
        """Search one stable descriptor-backed workspace snapshot."""
        from core.runtime.confined_filesystem_search import search_confined_text

        return search_confined_text(
            self,
            relative_path,
            query=query,
            max_depth=max_depth,
            page_size=page_size,
            cursor=cursor,
            case_sensitive=case_sensitive,
        )

    def move_path(
        self,
        source_path: str,
        destination_path: str,
        *,
        expected_resource_identity: str,
        expected_resource_revision: str,
        create_parents: bool = False,
        mutation_guard: FilesystemMutationGuard | None = None,
    ) -> ConfinedFilesystemResult:
        """Atomically rename one version-fenced file or directory."""
        from core.runtime.confined_filesystem_mutations import move_confined_path

        return move_confined_path(
            self,
            source_path,
            destination_path,
            expected_resource_identity=expected_resource_identity,
            expected_resource_revision=expected_resource_revision,
            create_parents=create_parents,
            mutation_guard=mutation_guard,
        )

    def delete_path(
        self,
        relative_path: str,
        *,
        expected_resource_identity: str,
        expected_resource_revision: str,
        recursive: bool = False,
        mutation_guard: FilesystemMutationGuard | None = None,
    ) -> ConfinedFilesystemResult:
        """Delete one version-fenced path without following links."""
        from core.runtime.confined_filesystem_delete import delete_confined_path

        return delete_confined_path(
            self,
            relative_path,
            expected_resource_identity=expected_resource_identity,
            expected_resource_revision=expected_resource_revision,
            recursive=recursive,
            mutation_guard=mutation_guard,
        )

    def duplicate_root_fd(self) -> int:
        """Return a verified duplicate for a confined child-process mount."""
        if self._root_fd < 0 or self._root_stat is None:
            raise RuntimeToolError("filesystem_root_unavailable")
        duplicate = os.dup(self._root_fd)
        try:
            if not _same_identity(os.fstat(duplicate), self._root_stat):
                raise RuntimeToolError("filesystem_root_moved")
            self._assert_root_location(duplicate)
            return duplicate
        except Exception:
            os.close(duplicate)
            raise

    def open_platform_runtime_fd(self, runtime_root: Path) -> int:
        """Open the protected direct `runtime/` child without following links."""
        configured = Path(os.path.abspath(os.fspath(runtime_root)))
        if configured != self.workspace_root / "runtime":
            raise RuntimeToolError("workspace_shell_root_mismatch")
        root_fd = self.duplicate_root_fd()
        try:
            try:
                os.mkdir("runtime", 0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
            runtime_fd = os.open(
                "runtime",
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                dir_fd=root_fd,
            )
            opened = os.fstat(runtime_fd)
            if not stat.S_ISDIR(opened.st_mode):
                os.close(runtime_fd)
                raise RuntimeToolError("filesystem_path_not_directory")
            return runtime_fd
        except RuntimeToolError:
            raise
        except OSError as error:
            raise RuntimeToolError("filesystem_path_outside_workspace") from error
        finally:
            os.close(root_fd)

    def open_shell_cwd(self, relative_path: str) -> _OpenChain:
        """Return a retained directory chain suitable for child ``fchdir``."""
        components = self._components(relative_path, allow_root=True)
        chain = self._open_chain(components)
        try:
            self._assert_chain(chain)
            self._hook("shell_cwd_opened", relative_path)
            self._assert_chain(chain)
            return chain
        except Exception:
            chain.close()
            raise

    def path_is_directory(self, relative_path: str) -> bool:
        """Inspect one exact final entry without following it or its parents."""
        components = self._components(relative_path, allow_root=True)
        if not components:
            return True
        with self._open_chain(components[:-1]) as chain:
            try:
                result = os.stat(
                    components[-1],
                    dir_fd=chain.leaf_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return False
            except OSError as error:
                raise RuntimeToolError("filesystem_resource_changed") from error
            if stat.S_ISLNK(result.st_mode):
                raise RuntimeToolError("filesystem_symlink_denied")
            self._assert_chain(chain)
            return stat.S_ISDIR(result.st_mode)

    def path_mode(self, relative_path: str, *, directory: bool) -> int:
        """Return permission bits for one exact confined entry."""
        return self.path_metadata(relative_path, directory=directory).mode

    def path_metadata(
        self,
        relative_path: str,
        *,
        directory: bool,
    ) -> ConfinedPathMetadata:
        """Return bounded metadata for one descriptor-confined path."""
        components = self._components(relative_path, allow_root=directory)
        if directory:
            with self._open_chain(components) as chain:
                result = os.fstat(chain.leaf_fd)
                if not stat.S_ISDIR(result.st_mode):
                    raise RuntimeToolError("filesystem_resource_changed")
                metadata = capture_fd_metadata(chain.leaf_fd)
                self._assert_chain(chain)
                return metadata
        with self._open_chain(components[:-1]) as chain:
            try:
                fd = os.open(
                    components[-1],
                    os.O_RDONLY | _NOFOLLOW | _CLOEXEC,
                    dir_fd=chain.leaf_fd,
                )
            except OSError as error:
                raise RuntimeToolError("filesystem_resource_changed") from error
            try:
                result = os.fstat(fd)
                if not stat.S_ISREG(result.st_mode):
                    raise RuntimeToolError("filesystem_resource_changed")
                metadata = capture_fd_metadata(fd)
                self._assert_final_link(chain.leaf_fd, components[-1], result)
                self._assert_chain(chain)
                return metadata
            finally:
                os.close(fd)

    def assert_shell_cwd(self, chain: _OpenChain) -> None:
        self._assert_chain(chain)

    def _scan_tree(
        self,
        requested_fd: int,
        *,
        base_components: tuple[str, ...],
        max_depth: int,
    ) -> tuple[
        list[dict[str, object]],
        list[_DirectoryAnchor],
        list[_EntryAnchor],
    ]:
        root_duplicate = os.dup(requested_fd)
        root_stat = os.fstat(root_duplicate)
        anchors = [_DirectoryAnchor(None, root_duplicate, None, self._relative(base_components), root_stat)]
        queue = deque([(anchors[0], base_components, 1)])
        entries: list[dict[str, object]] = []
        entry_anchors: list[_EntryAnchor] = []
        try:
            while queue:
                anchor, components, depth = queue.popleft()
                before = os.fstat(anchor.fd)
                try:
                    names = sorted(os.listdir(anchor.fd))
                except OSError as error:
                    raise RuntimeToolError("filesystem_list_failed") from error
                for name in names:
                    if name == ".git" or (not components and name == "runtime"):
                        continue
                    try:
                        name.encode("utf-8", errors="strict")
                        item_stat = os.stat(name, dir_fd=anchor.fd, follow_symlinks=False)
                    except UnicodeError as error:
                        raise RuntimeToolError("filesystem_name_not_utf8") from error
                    except OSError as error:
                        raise RuntimeToolError("filesystem_snapshot_changed") from error
                    item_components = (*components, name)
                    entry_anchors.append(_EntryAnchor(anchor.fd, name, item_stat))
                    item_type = _file_type(item_stat.st_mode)
                    item_observation = self._observation(
                        "filesystem_directory" if item_type == "directory" else "filesystem_file",
                        self._relative(item_components),
                        item_stat,
                    )
                    entries.append(
                        {
                            "path": item_observation.resource_ref,
                            "name": name,
                            "type": item_type,
                            "depth": depth,
                            "size_bytes": item_stat.st_size if item_type == "file" else None,
                            "resource_identity": item_observation.resource_identity,
                            "resource_revision": item_observation.resource_revision,
                        }
                    )
                    if len(entries) > MAX_CONFINED_LIST_ENTRIES:
                        raise RuntimeToolError("filesystem_list_too_large")
                    if item_type == "directory" and depth < max_depth:
                        self._hook(
                            "list_before_directory_open",
                            self._relative(item_components),
                        )
                        try:
                            child_fd = os.open(
                                name,
                                os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                                dir_fd=anchor.fd,
                            )
                        except OSError as error:
                            raise RuntimeToolError("filesystem_snapshot_changed") from error
                        opened = os.fstat(child_fd)
                        if not _same_identity(opened, item_stat):
                            os.close(child_fd)
                            raise RuntimeToolError("filesystem_snapshot_changed")
                        child = _DirectoryAnchor(
                            anchor.fd,
                            child_fd,
                            name,
                            self._relative(item_components),
                            opened,
                        )
                        anchors.append(child)
                        queue.append((child, item_components, depth + 1))
                self._assert_same_version(
                    before,
                    os.fstat(anchor.fd),
                    "filesystem_snapshot_changed",
                )
            entries.sort(key=lambda item: (int(item["depth"]), str(item["path"])))
            return entries, anchors, entry_anchors
        except Exception:
            for anchor in reversed(anchors):
                try:
                    os.close(anchor.fd)
                except OSError:
                    pass
            raise

    def _open_chain(
        self,
        components: tuple[str, ...],
        *,
        create_missing: bool = False,
    ) -> _OpenChain:
        if self._root_fd < 0 or self._root_stat is None:
            raise RuntimeToolError("filesystem_root_unavailable")
        try:
            root_fd = os.dup(self._root_fd)
        except OSError as error:
            raise RuntimeToolError("filesystem_root_unavailable") from error
        if not _same_identity(os.fstat(root_fd), self._root_stat):
            os.close(root_fd)
            raise RuntimeToolError("filesystem_root_moved")
        anchors = [
            _DirectoryAnchor(None, root_fd, None, ".", os.fstat(root_fd))
        ]
        try:
            for index, name in enumerate(components):
                parent_fd = anchors[-1].fd
                try:
                    child_fd = os.open(
                        name,
                        os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                        dir_fd=parent_fd,
                    )
                except FileNotFoundError:
                    if not create_missing:
                        raise RuntimeToolError("filesystem_path_not_found")
                    try:
                        os.mkdir(name, 0o2770, dir_fd=parent_fd)
                        child_fd = os.open(
                            name,
                            os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                            dir_fd=parent_fd,
                        )
                    except OSError as error:
                        raise RuntimeToolError("filesystem_write_failed") from error
                except OSError as error:
                    raise RuntimeToolError("filesystem_path_outside_workspace") from error
                opened = os.fstat(child_fd)
                if not stat.S_ISDIR(opened.st_mode):
                    os.close(child_fd)
                    raise RuntimeToolError("filesystem_path_not_directory")
                anchors.append(
                    _DirectoryAnchor(
                        parent_fd,
                        child_fd,
                        name,
                        self._relative(components[: index + 1]),
                        opened,
                    )
                )
            return _OpenChain(anchors)
        except Exception:
            _OpenChain(anchors).close()
            raise

    def _open_configured_root(self) -> int:
        current = os.open("/", os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC)
        try:
            for component in self.workspace_root.parts[1:]:
                next_fd = os.open(
                    component,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
                    dir_fd=current,
                )
                os.close(current)
                current = next_fd
            return current
        except OSError as error:
            os.close(current)
            raise RuntimeToolError("filesystem_root_unavailable") from error

    def _assert_chain(self, chain: _OpenChain) -> None:
        self._assert_root_location(chain.anchors[0].fd)
        for anchor in chain.anchors[1:]:
            self._assert_anchor(anchor, version=False)

    def _assert_anchor(self, anchor: _DirectoryAnchor, *, version: bool) -> None:
        if anchor.parent_fd is not None and anchor.name is not None:
            try:
                linked = os.stat(anchor.name, dir_fd=anchor.parent_fd, follow_symlinks=False)
            except OSError as error:
                raise RuntimeToolError("filesystem_resource_changed") from error
            current = os.fstat(anchor.fd)
            if not _same_identity(linked, current) or not stat.S_ISDIR(linked.st_mode):
                raise RuntimeToolError("filesystem_resource_changed")
            if version:
                self._assert_same_version(
                    anchor.opened_stat,
                    current,
                    "filesystem_snapshot_changed",
                )

    @staticmethod
    def _assert_entry_snapshot(anchor: _EntryAnchor) -> None:
        try:
            current = os.stat(
                anchor.name,
                dir_fd=anchor.parent_fd,
                follow_symlinks=False,
            )
        except OSError as error:
            raise RuntimeToolError("filesystem_snapshot_changed") from error
        ConfinedWorkspaceFilesystem._assert_same_version(
            anchor.opened_stat,
            current,
            "filesystem_snapshot_changed",
        )

    def _assert_root_location(self, root_fd: int) -> None:
        proc_path = f"/proc/self/fd/{root_fd}"
        try:
            current_path = os.readlink(proc_path)
        except OSError as error:
            raise RuntimeToolError("filesystem_root_identity_unavailable") from error
        if current_path != os.fspath(self.workspace_root):
            raise RuntimeToolError("filesystem_root_moved")

    @staticmethod
    def _assert_final_link(parent_fd: int, name: str, opened: os.stat_result) -> None:
        try:
            linked = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as error:
            raise RuntimeToolError("filesystem_resource_changed") from error
        if not _same_identity(linked, opened) or stat.S_ISLNK(linked.st_mode):
            raise RuntimeToolError("filesystem_resource_changed")

    @staticmethod
    def _assert_same_version(
        before: os.stat_result,
        after: os.stat_result,
        reason_code: str,
    ) -> None:
        if _version_fields(before) != _version_fields(after):
            raise RuntimeToolError(reason_code)

    @staticmethod
    def _open_file(parent_fd: int, name: str, *, write: bool) -> int:
        flags = (os.O_WRONLY if write else os.O_RDONLY) | _NOFOLLOW | _CLOEXEC
        try:
            return os.open(name, flags, dir_fd=parent_fd)
        except OSError as error:
            raise RuntimeToolError("filesystem_path_outside_workspace") from error

    @staticmethod
    def _reject_existing_symlink(parent_fd: int, name: str) -> None:
        try:
            existing = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        except OSError as error:
            raise RuntimeToolError("filesystem_write_failed") from error
        if stat.S_ISLNK(existing.st_mode) or stat.S_ISDIR(existing.st_mode):
            raise RuntimeToolError("filesystem_path_outside_workspace")

    @staticmethod
    def _unlink_if_identity(parent_fd: int, name: str, expected: os.stat_result) -> None:
        try:
            linked = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if _same_identity(linked, expected):
                os.unlink(name, dir_fd=parent_fd)
        except OSError:
            pass

    def _observation(
        self,
        resource_kind: str,
        resource_ref: str,
        result: os.stat_result,
    ) -> FilesystemResourceObservation:
        identity = f"linux:{result.st_dev}:{result.st_ino}"
        revision = _resource_revision(result)
        return FilesystemResourceObservation(
            workspace_id=self.workspace_id,
            resource_kind=resource_kind,
            resource_ref=resource_ref,
            resource_identity=identity,
            resource_revision=revision,
            resource_digest=revision,
        )

    def _classification(
        self,
        observation: FilesystemResourceObservation,
        provenance: str,
    ) -> CanonicalSourceClassification:
        if self.classification_resolver is None:
            return fail_closed_classification(
                provenance=provenance,
                source_ref=observation.resource_ref,
                source_revision=observation.resource_revision,
                source_digest=observation.resource_digest,
                resource_identity=observation.resource_identity,
            )
        try:
            classification = self.classification_resolver(observation, provenance)
        except Exception as error:
            raise RuntimeToolError("filesystem_classification_unavailable") from error
        normalized = join_classifications((classification,)).sources[0]
        if (
            normalized.provenance != provenance
            or normalized.source_ref != observation.resource_ref
            or normalized.source_revision != observation.resource_revision
            or normalized.source_digest != observation.resource_digest
            or normalized.resource_identity != observation.resource_identity
        ):
            return fail_closed_classification(
                provenance=provenance,
                source_ref=observation.resource_ref,
                source_revision=observation.resource_revision,
                source_digest=observation.resource_digest,
                resource_identity=observation.resource_identity,
            )
        return normalized

    def _require_expected(
        self,
        observation: FilesystemResourceObservation,
        *,
        identity: str | None,
        revision: str | None,
    ) -> None:
        if identity is not None and identity != observation.resource_identity:
            raise RuntimeToolError("filesystem_resource_changed")
        if revision is not None and revision != observation.resource_revision:
            raise RuntimeToolError("filesystem_resource_changed")

    def _components(self, value: str, *, allow_root: bool) -> tuple[str, ...]:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise RuntimeToolError("filesystem_path_invalid")
        path = PurePosixPath(value)
        if path.is_absolute():
            raise RuntimeToolError("filesystem_path_outside_workspace")
        components = tuple(part for part in path.parts if part != ".")
        if (
            len(components) > MAX_CONFINED_PATH_COMPONENTS
            or any(part in {"", ".", "..", ".git"} for part in components)
            or (components and components[0] == "runtime")
        ):
            raise RuntimeToolError("filesystem_path_outside_workspace")
        if not components and not allow_root:
            raise RuntimeToolError("filesystem_path_invalid")
        return components

    @staticmethod
    def _relative(components: tuple[str, ...]) -> str:
        return "/".join(components) or "."

    def _encode_cursor(self, payload: dict[str, object]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self.cursor_key, _CURSOR_DOMAIN + raw, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(signature + raw).decode("ascii").rstrip("=")

    def _decode_cursor(self, value: str) -> dict[str, object]:
        try:
            padded = value + "=" * (-len(value) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
            signature, raw = decoded[:32], decoded[32:]
            expected = hmac.new(self.cursor_key, _CURSOR_DOMAIN + raw, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            payload = json.loads(raw)
            required = {
                "v",
                "path",
                "max_depth",
                "page_size",
                "snapshot_id",
                "resource_identity",
                "resource_revision",
                "offset",
            }
            if not isinstance(payload, dict) or set(payload) != required or payload["v"] != 1:
                raise ValueError
            return payload
        except (UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeToolError("filesystem_cursor_invalid") from error

    def _hook(self, event: str, path: str) -> None:
        if self.race_hook is not None:
            self.race_hook(event, path)


def _rollback_confined_write(
    parent_fd: int,
    final_name: str,
    temporary_name: str,
    committed_stat: os.stat_result,
    *,
    previous_stat: os.stat_result | None,
    rollback_kind: str | None,
    old_entry_retained: bool,
) -> bool:
    """Restore the exact pre-write namespace only while both identities match."""
    try:
        current = os.stat(final_name, dir_fd=parent_fd, follow_symlinks=False)
        if not same_identity(current, committed_stat):
            return False
        if rollback_kind == "created":
            os.unlink(final_name, dir_fd=parent_fd)
            os.fsync(parent_fd)
            return True
        if (
            rollback_kind != "exchanged"
            or not old_entry_retained
            or previous_stat is None
        ):
            return False
        retained = os.stat(
            temporary_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if not same_identity(retained, previous_stat):
            return False
        rename_exchange(
            parent_fd,
            temporary_name,
            parent_fd,
            final_name,
        )
        restored = os.stat(final_name, dir_fd=parent_fd, follow_symlinks=False)
        displaced = os.stat(
            temporary_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if not same_identity(restored, previous_stat) or not same_identity(
            displaced,
            committed_stat,
        ):
            return False
        os.unlink(temporary_name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        return True
    except Exception:
        return False


def _same_exchange_version(left: os.stat_result, right: os.stat_result) -> bool:
    """Compare fields not intrinsically changed by a directory-entry exchange."""
    fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
    )
    return all(getattr(left, field) == getattr(right, field) for field in fields)


def _resource_revision(result: os.stat_result) -> str:
    value = ":".join(str(item) for item in _version_fields(result))
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _version_fields(result: os.stat_result) -> tuple[int, ...]:
    return (
        result.st_dev,
        result.st_ino,
        result.st_mode,
        result.st_size,
        result.st_mtime_ns,
        result.st_ctime_ns,
    )


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _file_type(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "other"


def _snapshot_digest(
    observation: FilesystemResourceObservation,
    entries: list[dict[str, object]],
    max_depth: int,
) -> str:
    raw = json.dumps(
        {
            "resource_identity": observation.resource_identity,
            "resource_revision": observation.resource_revision,
            "max_depth": max_depth,
            "entries": entries,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _utf8_prefix(payload: bytes) -> bytes:
    if not payload:
        return payload
    for trim in range(0, min(4, len(payload)) + 1):
        candidate = payload[: len(payload) - trim] if trim else payload
        try:
            candidate.decode("utf-8")
            return candidate
        except UnicodeDecodeError as error:
            if error.start < max(0, len(payload) - 4):
                raise RuntimeToolError("filesystem_read_not_utf8") from error
    raise RuntimeToolError("filesystem_read_not_utf8")


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written < 1:
            raise RuntimeToolError("filesystem_write_failed")
        offset += written
