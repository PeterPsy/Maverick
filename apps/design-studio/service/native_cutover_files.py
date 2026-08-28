"""Fail-closed filesystem primitives for the one-time native data cutover."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
from typing import Any, Iterable


class NativeCutoverFileError(RuntimeError):
    """A cutover path or byte-integrity invariant failed."""


def real_directory(path: Path, *, label: str, create: bool = False) -> Path:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise NativeCutoverFileError(f"{label} is unavailable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise NativeCutoverFileError(f"{label} must be a real directory")
    return resolved


def copy_verified_tree(source: Path, destination: Path) -> dict[str, Any]:
    """Copy one stable regular-file tree and prove byte-identical output."""
    source = real_directory(source, label="cutover source tree")
    if destination.exists() or destination.is_symlink():
        raise NativeCutoverFileError("cutover destination already exists")
    before = tree_evidence(source)
    shutil.copytree(source, destination, symlinks=False, copy_function=shutil.copy2)
    after_source = tree_evidence(source)
    copied = tree_evidence(destination)
    if before != after_source:
        shutil.rmtree(destination, ignore_errors=True)
        raise NativeCutoverFileError("cutover source changed during backup")
    if before != copied:
        shutil.rmtree(destination, ignore_errors=True)
        raise NativeCutoverFileError("cutover backup differs from its source")
    fsync_tree(destination)
    return before


def tree_evidence(root: Path) -> dict[str, Any]:
    """Hash names, modes, sizes, and bytes while rejecting links/special files."""
    root = real_directory(root, label="cutover tree")
    digest = sha256()
    root_mode = stat.S_IMODE(root.lstat().st_mode)
    digest.update(f"D\0.\0{root_mode:o}\n".encode("utf-8"))
    file_count = 0
    directory_count = 1
    total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISDIR(metadata.st_mode):
            directory_count += 1
            digest.update(f"D\0{relative}\0{mode:o}\n".encode("utf-8"))
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise NativeCutoverFileError(f"cutover tree contains an unsafe entry: {relative}")
        file_digest = file_sha256(path)
        file_count += 1
        total_bytes += metadata.st_size
        digest.update(
            f"F\0{relative}\0{mode:o}\0{metadata.st_size}\0{file_digest}\n".encode("utf-8")
        )
    return {
        "sha256": digest.hexdigest(),
        "root_mode": root_mode,
        "file_count": file_count,
        "directory_count": directory_count,
        "total_bytes": total_bytes,
    }


def copy_legacy_files(
    app_data_root: Path,
    destination: Path,
    relative_paths: Iterable[str],
) -> dict[str, str]:
    """Copy an explicit allowlist of legacy correlation/config files."""
    app_data_root = real_directory(app_data_root, label="Design Studio data root")
    destination.mkdir(mode=0o700, parents=True)
    copied: dict[str, str] = {}
    for relative in relative_paths:
        source = _safe_relative_file(app_data_root, relative)
        if source is None:
            continue
        target = destination / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)
        copied[relative] = file_sha256(target)
    fsync_tree(destination)
    return copied


def atomic_write_json(path: Path, payload: dict[str, Any], *, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    body = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True).encode("utf-8") + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, mode)
    try:
        remaining = memoryview(body)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("atomic JSON write made no progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
        os.chmod(path, mode)
        fsync_directory(path.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def make_tree_read_only(root: Path) -> None:
    root = real_directory(root, label="legacy OpenDesign source")
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise NativeCutoverFileError("legacy source contains a symlink")
        if stat.S_ISREG(metadata.st_mode):
            path.chmod(stat.S_IMODE(metadata.st_mode) & ~0o222)
        elif stat.S_ISDIR(metadata.st_mode):
            path.chmod(stat.S_IMODE(metadata.st_mode) & ~0o222)
        else:
            raise NativeCutoverFileError("legacy source contains a special file")
    root.chmod(stat.S_IMODE(root.lstat().st_mode) & ~0o222)
    fsync_tree(root)


def make_files_read_only(app_data_root: Path, relative_paths: Iterable[str]) -> list[str]:
    root = real_directory(app_data_root, label="Design Studio data root")
    changed: list[str] = []
    for relative in relative_paths:
        path = _safe_relative_file(root, relative)
        if path is None:
            continue
        path.chmod(stat.S_IMODE(path.lstat().st_mode) & ~0o222)
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        fsync_directory(path.parent)
        changed.append(relative)
    return changed


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fsync_tree(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
        fsync_directory(path)
    fsync_directory(root)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _safe_relative_file(root: Path, relative: str) -> Path | None:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise NativeCutoverFileError("legacy file allowlist contains an unsafe path")
    path = root / candidate
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        return None
    if root not in resolved.parents or stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise NativeCutoverFileError(f"legacy correlation file is unsafe: {relative}")
    return path
