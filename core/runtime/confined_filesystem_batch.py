"""Rollback-safe descriptor-confined text transactions."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import stat

from core.runtime.confined_filesystem import (
    ConfinedFilesystemResult,
    ConfinedWorkspaceFilesystem,
    FilesystemMutationGuard,
    FilesystemResourceObservation,
)
from core.runtime.confined_filesystem_mutation_support import (
    rename_exchange,
    rename_noreplace,
    same_identity,
)
from core.runtime.tool_errors import RuntimeToolError


_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


@dataclass(frozen=True)
class ConfinedTextBatchWrite:
    """One create-or-replace operation in an all-or-rollback text batch."""

    path: str
    content: str
    expected_resource_identity: str | None
    expected_resource_revision: str | None
    mutation_guard: FilesystemMutationGuard


@dataclass
class _StagedWrite:
    request: ConfinedTextBatchWrite
    components: tuple[str, ...]
    chain: object
    temporary_name: str
    temporary_fd: int
    payload: bytes
    previous_stat: os.stat_result | None
    previous_observation: FilesystemResourceObservation | None
    committed_stat: os.stat_result | None = None
    committed: bool = False
    old_entry_retained: bool = False


def write_confined_text_batch(
    filesystem: ConfinedWorkspaceFilesystem,
    writes: tuple[ConfinedTextBatchWrite, ...],
    *,
    transaction_directory: Path,
) -> tuple[ConfinedFilesystemResult, ...]:
    """Commit every exact text write or restore the complete prior namespace."""
    if len({item.path for item in writes}) != len(writes):
        raise RuntimeToolError("filesystem_batch_duplicate_path")
    transaction_fd = _open_transaction_directory(transaction_directory)
    staged: list[_StagedWrite] = []
    preserve_transaction = False
    try:
        for request in writes:
            staged.append(_stage_write(filesystem, transaction_fd, request))
        _verify_staged(filesystem, staged)
        for item in staged:
            _commit_staged(filesystem, transaction_fd, item)
        for item in staged:
            _verify_committed(filesystem, item)
        results = tuple(_result(filesystem, item) for item in staged)
        _release_backups(transaction_fd, staged)
        return results
    except RuntimeToolError as error:
        if not _rollback_batch(filesystem, transaction_fd, staged):
            preserve_transaction = True
            raise RuntimeToolError("tool_execution_unknown") from error
        raise
    except OSError as error:
        if not _rollback_batch(filesystem, transaction_fd, staged):
            preserve_transaction = True
            raise RuntimeToolError("tool_execution_unknown") from error
        raise RuntimeToolError("filesystem_write_failed") from error
    except Exception as error:
        if not _rollback_batch(filesystem, transaction_fd, staged):
            preserve_transaction = True
            raise RuntimeToolError("tool_execution_unknown") from error
        raise RuntimeToolError("filesystem_write_failed") from error
    finally:
        for item in reversed(staged):
            try:
                os.close(item.temporary_fd)
            except OSError:
                pass
            item.chain.close()  # type: ignore[attr-defined]
        if not preserve_transaction:
            _remove_staged_entries(transaction_fd, staged)
        os.close(transaction_fd)


def _open_transaction_directory(path: Path) -> int:
    try:
        return os.open(path, os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC)
    except OSError as error:
        raise RuntimeToolError("filesystem_batch_transaction_unavailable") from error


def _stage_write(
    filesystem: ConfinedWorkspaceFilesystem,
    transaction_fd: int,
    request: ConfinedTextBatchWrite,
) -> _StagedWrite:
    if not isinstance(request.content, str):
        raise RuntimeToolError("tool_arguments_invalid")
    if bool(request.expected_resource_identity) != bool(
        request.expected_resource_revision
    ):
        raise RuntimeToolError("filesystem_expected_version_incomplete")
    components = filesystem._components(request.path, allow_root=False)
    chain = filesystem._open_chain(components[:-1])
    temporary_name = f"write-{secrets.token_hex(16)}"
    temporary_fd: int | None = None
    try:
        previous_stat = _lstat_optional(chain.leaf_fd, components[-1])
        previous_observation = None
        if previous_stat is not None:
            if stat.S_ISLNK(previous_stat.st_mode):
                raise RuntimeToolError("filesystem_symlink_denied")
            if not stat.S_ISREG(previous_stat.st_mode):
                raise RuntimeToolError("filesystem_path_not_file")
            previous_observation = filesystem._observation(
                "filesystem_file",
                filesystem._relative(components),
                previous_stat,
            )
        if request.expected_resource_identity is None:
            if previous_stat is not None:
                raise RuntimeToolError("filesystem_path_exists")
        else:
            if previous_observation is None:
                raise RuntimeToolError("filesystem_resource_changed")
            filesystem._require_expected(
                previous_observation,
                identity=request.expected_resource_identity,
                revision=request.expected_resource_revision,
            )
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
            0o600,
            dir_fd=transaction_fd,
        )
        payload = request.content.encode("utf-8")
        _write_all(temporary_fd, payload)
        os.fsync(temporary_fd)
        filesystem._hook("write_temporary_ready", request.path)
        request.mutation_guard.verify_before()
        filesystem._assert_chain(chain)
        _revalidate_original(filesystem, chain, components[-1], previous_stat)
        return _StagedWrite(
            request=request,
            components=components,
            chain=chain,
            temporary_name=temporary_name,
            temporary_fd=temporary_fd,
            payload=payload,
            previous_stat=previous_stat,
            previous_observation=previous_observation,
        )
    except Exception:
        if temporary_fd is not None:
            os.close(temporary_fd)
        try:
            os.unlink(temporary_name, dir_fd=transaction_fd)
        except OSError:
            pass
        chain.close()
        raise


def _verify_staged(
    filesystem: ConfinedWorkspaceFilesystem,
    staged: list[_StagedWrite],
) -> None:
    for item in staged:
        item.request.mutation_guard.verify_before()
        filesystem._assert_chain(item.chain)  # type: ignore[arg-type]
        _revalidate_original(
            filesystem,
            item.chain,
            item.components[-1],
            item.previous_stat,
        )


def _commit_staged(
    filesystem: ConfinedWorkspaceFilesystem,
    transaction_fd: int,
    item: _StagedWrite,
) -> None:
    parent_fd = item.chain.leaf_fd  # type: ignore[attr-defined]
    final_name = item.components[-1]
    if item.previous_stat is None:
        rename_noreplace(
            transaction_fd,
            item.temporary_name,
            parent_fd,
            final_name,
        )
        item.committed = True
        item.committed_stat = os.fstat(item.temporary_fd)
    else:
        rename_exchange(
            transaction_fd,
            item.temporary_name,
            parent_fd,
            final_name,
        )
        item.committed = True
        item.old_entry_retained = True
        item.committed_stat = os.fstat(item.temporary_fd)
        retained = os.stat(
            item.temporary_name,
            dir_fd=transaction_fd,
            follow_symlinks=False,
        )
        if not same_identity(retained, item.previous_stat) or not _same_exchange_version(
            retained,
            item.previous_stat,
        ):
            raise RuntimeToolError("filesystem_resource_changed")
    os.fsync(parent_fd)
    os.fsync(transaction_fd)
    filesystem._hook("write_committed", item.request.path)
    _verify_committed(filesystem, item)


def _verify_committed(
    filesystem: ConfinedWorkspaceFilesystem,
    item: _StagedWrite,
) -> None:
    if not item.committed or item.committed_stat is None:
        raise RuntimeToolError("filesystem_resource_changed")
    after = os.fstat(item.temporary_fd)
    filesystem._assert_same_version(
        item.committed_stat,
        after,
        "filesystem_resource_changed",
    )
    item.committed_stat = after
    filesystem._assert_final_link(
        item.chain.leaf_fd,  # type: ignore[attr-defined]
        item.components[-1],
        after,
    )
    filesystem._assert_chain(item.chain)  # type: ignore[arg-type]
    item.request.mutation_guard.verify_after()


def _result(
    filesystem: ConfinedWorkspaceFilesystem,
    item: _StagedWrite,
) -> ConfinedFilesystemResult:
    assert item.committed_stat is not None
    observation = filesystem._observation(
        "filesystem_file",
        filesystem._relative(item.components),
        item.committed_stat,
    )
    return ConfinedFilesystemResult(
        {
            "path": observation.resource_ref,
            "byte_count": len(item.payload),
            "created": item.previous_stat is None,
            "replaced": item.previous_stat is not None,
            "previous_resource_revision": (
                None
                if item.previous_observation is None
                else item.previous_observation.resource_revision
            ),
            "previous_resource_digest": (
                None
                if item.previous_observation is None
                else item.previous_observation.resource_digest
            ),
            "resource_identity": observation.resource_identity,
            "resource_revision": observation.resource_revision,
            "resource_digest": observation.resource_digest,
        },
        filesystem._classification(observation, "tool_result"),
    )


def _rollback_batch(
    filesystem: ConfinedWorkspaceFilesystem,
    transaction_fd: int,
    staged: list[_StagedWrite],
) -> bool:
    restored = True
    for item in reversed(staged):
        if not item.committed:
            continue
        if not _rollback_item(filesystem, transaction_fd, item):
            restored = False
    return restored


def _rollback_item(
    filesystem: ConfinedWorkspaceFilesystem,
    transaction_fd: int,
    item: _StagedWrite,
) -> bool:
    assert item.committed_stat is not None
    parent_fd = item.chain.leaf_fd  # type: ignore[attr-defined]
    final_name = item.components[-1]
    try:
        current = os.stat(final_name, dir_fd=parent_fd, follow_symlinks=False)
        filesystem._assert_same_version(
            item.committed_stat,
            current,
            "filesystem_resource_changed",
        )
        if item.previous_stat is None:
            os.unlink(final_name, dir_fd=parent_fd)
        else:
            if not item.old_entry_retained:
                return False
            retained = os.stat(
                item.temporary_name,
                dir_fd=transaction_fd,
                follow_symlinks=False,
            )
            if not same_identity(retained, item.previous_stat):
                return False
            rename_exchange(
                transaction_fd,
                item.temporary_name,
                parent_fd,
                final_name,
            )
            restored = os.stat(final_name, dir_fd=parent_fd, follow_symlinks=False)
            displaced = os.stat(
                item.temporary_name,
                dir_fd=transaction_fd,
                follow_symlinks=False,
            )
            if not same_identity(restored, item.previous_stat) or not same_identity(
                displaced,
                item.committed_stat,
            ):
                return False
            os.unlink(item.temporary_name, dir_fd=transaction_fd)
            item.old_entry_retained = False
        os.fsync(parent_fd)
        os.fsync(transaction_fd)
        item.committed = False
        return True
    except Exception:
        return False


def _release_backups(
    transaction_fd: int,
    staged: list[_StagedWrite],
) -> None:
    for item in staged:
        if item.old_entry_retained:
            os.unlink(item.temporary_name, dir_fd=transaction_fd)
            item.old_entry_retained = False
    os.fsync(transaction_fd)


def _remove_staged_entries(
    transaction_fd: int,
    staged: list[_StagedWrite],
) -> None:
    for item in staged:
        try:
            os.unlink(item.temporary_name, dir_fd=transaction_fd)
        except OSError:
            pass


def _lstat_optional(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise RuntimeToolError("filesystem_resource_changed") from error


def _revalidate_original(
    filesystem: ConfinedWorkspaceFilesystem,
    chain,
    name: str,
    expected: os.stat_result | None,
) -> None:
    current = _lstat_optional(chain.leaf_fd, name)
    if expected is None:
        if current is not None:
            raise RuntimeToolError("filesystem_resource_changed")
        return
    if current is None:
        raise RuntimeToolError("filesystem_resource_changed")
    filesystem._assert_same_version(
        expected,
        current,
        "filesystem_resource_changed",
    )


def _same_exchange_version(left: os.stat_result, right: os.stat_result) -> bool:
    return all(
        getattr(left, field) == getattr(right, field)
        for field in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
        )
    )


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written < 1:
            raise RuntimeToolError("filesystem_write_failed")
        offset += written


__all__ = ["ConfinedTextBatchWrite", "write_confined_text_batch"]
