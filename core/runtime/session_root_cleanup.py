"""Atomic staging and deferred physical purge for runtime-session roots."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import shutil
import stat

from core.runtime.confined_filesystem_mutation_support import rename_noreplace
from core.runtime.paths import runtime_session_root, workspace_runtime_root
from core.runtime.tool_errors import RuntimeToolError


RUNTIME_SESSION_DELETION_QUARANTINE = "session-deletion-quarantine"
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


class RuntimeSessionRootCleanupError(Exception):
    """Report a safe stable reason for runtime-root cleanup failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def runtime_session_deletion_quarantine_root(
    workspace_id: str,
    *,
    start_path: Path | None = None,
) -> Path:
    """Return Core's private deferred-deletion directory for one workspace."""
    return workspace_runtime_root(workspace_id, start_path=start_path) / RUNTIME_SESSION_DELETION_QUARANTINE


def stage_runtime_session_root_deletion(
    runtime_root: Path,
    *,
    workspace_id: str,
    session_id: str,
    start_path: Path,
) -> Path | None:
    """Atomically remove a canonical session root from view and queue its purge."""
    expected_root = runtime_session_root(
        workspace_id=workspace_id,
        session_id=session_id,
        start_path=start_path,
    )
    if os.path.abspath(runtime_root) != os.path.abspath(expected_root):
        raise RuntimeSessionRootCleanupError("runtime_session_root_unsafe")

    sessions_root = expected_root.parent
    try:
        sessions_fd = os.open(sessions_root, _DIRECTORY_FLAGS)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise RuntimeSessionRootCleanupError("runtime_session_root_unsafe") from error
    try:
        try:
            source_stat = os.stat(expected_root.name, dir_fd=sessions_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISDIR(source_stat.st_mode):
            raise RuntimeSessionRootCleanupError("runtime_session_root_unsafe")

        quarantine_root = runtime_session_deletion_quarantine_root(
            workspace_id,
            start_path=start_path,
        )
        quarantine_fd = _open_quarantine_root(quarantine_root)
        try:
            destination_name = _move_to_unique_quarantine_entry(
                sessions_fd=sessions_fd,
                source_name=expected_root.name,
                quarantine_fd=quarantine_fd,
                session_id=session_id,
            )
            moved_stat = os.stat(destination_name, dir_fd=quarantine_fd, follow_symlinks=False)
            if (source_stat.st_dev, source_stat.st_ino) != (moved_stat.st_dev, moved_stat.st_ino):
                raise RuntimeSessionRootCleanupError("runtime_session_root_stage_unknown")
            os.fsync(sessions_fd)
            os.fsync(quarantine_fd)
            return quarantine_root / destination_name
        finally:
            os.close(quarantine_fd)
    finally:
        os.close(sessions_fd)


def purge_staged_runtime_roots(
    *,
    workspace_id: str,
    start_path: Path,
    max_roots: int,
) -> dict[str, object]:
    """Physically remove a bounded number of roots already hidden in quarantine."""
    if max_roots < 1:
        raise ValueError("Runtime-session root purge batch size must be positive.")
    quarantine_root = runtime_session_deletion_quarantine_root(
        workspace_id,
        start_path=start_path,
    )
    try:
        quarantine_fd = os.open(quarantine_root, _DIRECTORY_FLAGS)
    except FileNotFoundError:
        return _purge_result(workspace_id, attempted=0, purged=0, failures=[], remaining=0)
    except OSError as error:
        raise RuntimeSessionRootCleanupError("runtime_session_quarantine_unsafe") from error

    attempted = 0
    purged = 0
    failures: list[dict[str, str]] = []
    try:
        for entry_name in sorted(os.listdir(quarantine_fd))[:max_roots]:
            attempted += 1
            try:
                entry_stat = os.stat(entry_name, dir_fd=quarantine_fd, follow_symlinks=False)
                if stat.S_ISDIR(entry_stat.st_mode) and not stat.S_ISLNK(entry_stat.st_mode):
                    shutil.rmtree(entry_name, dir_fd=quarantine_fd)
                else:
                    os.unlink(entry_name, dir_fd=quarantine_fd)
                purged += 1
            except FileNotFoundError:
                purged += 1
            except Exception as error:
                failures.append({"entry": entry_name, "error_type": type(error).__name__})
        if purged:
            os.fsync(quarantine_fd)
        remaining = len(os.listdir(quarantine_fd))
    finally:
        os.close(quarantine_fd)
    return _purge_result(
        workspace_id,
        attempted=attempted,
        purged=purged,
        failures=failures,
        remaining=remaining,
    )


def _open_quarantine_root(quarantine_root: Path) -> int:
    try:
        quarantine_root.mkdir(mode=0o700, parents=False, exist_ok=True)
        quarantine_stat = os.lstat(quarantine_root)
        if stat.S_ISLNK(quarantine_stat.st_mode) or not stat.S_ISDIR(quarantine_stat.st_mode):
            raise RuntimeSessionRootCleanupError("runtime_session_quarantine_unsafe")
        quarantine_fd = os.open(quarantine_root, _DIRECTORY_FLAGS)
        os.fchmod(quarantine_fd, 0o700)
        return quarantine_fd
    except RuntimeSessionRootCleanupError:
        raise
    except OSError as error:
        raise RuntimeSessionRootCleanupError("runtime_session_quarantine_unavailable") from error


def _move_to_unique_quarantine_entry(
    *,
    sessions_fd: int,
    source_name: str,
    quarantine_fd: int,
    session_id: str,
) -> str:
    for _attempt in range(4):
        destination_name = f"{session_id}--{secrets.token_hex(16)}"
        try:
            rename_noreplace(
                sessions_fd,
                source_name,
                quarantine_fd,
                destination_name,
            )
            return destination_name
        except RuntimeToolError as error:
            if error.reason_code == "filesystem_path_exists":
                continue
            raise RuntimeSessionRootCleanupError("runtime_session_root_stage_failed") from error
        except OSError as error:
            raise RuntimeSessionRootCleanupError("runtime_session_root_stage_failed") from error
    raise RuntimeSessionRootCleanupError("runtime_session_quarantine_collision")


def _purge_result(
    workspace_id: str,
    *,
    attempted: int,
    purged: int,
    failures: list[dict[str, str]],
    remaining: int,
) -> dict[str, object]:
    return {
        "workspace_id": workspace_id,
        "attempted": attempted,
        "purged": purged,
        "failures": failures,
        "remaining": remaining,
    }
