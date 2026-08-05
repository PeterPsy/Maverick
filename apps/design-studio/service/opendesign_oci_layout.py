"""Apply verified OCI layers without allowing archive paths or links to escape."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
from typing import BinaryIO


class OciLayoutError(RuntimeError):
    """Fail-closed OCI layer or rootfs layout error."""


def apply_layers(layer_paths: tuple[Path, ...], rootfs: Path) -> None:
    if rootfs.exists() or rootfs.is_symlink():
        raise OciLayoutError("OpenDesign OCI rootfs destination must not exist")
    rootfs.mkdir(parents=True, mode=0o700)
    rootfs = rootfs.resolve(strict=True)
    try:
        for layer in layer_paths:
            apply_layer(layer, rootfs)
    except Exception:
        shutil.rmtree(rootfs)
        raise


def apply_layer(layer_path: Path, rootfs: Path) -> None:
    if layer_path.is_symlink() or not layer_path.is_file():
        raise OciLayoutError("OpenDesign OCI layer must be a real file")
    if rootfs.is_symlink() or not rootfs.is_dir():
        raise OciLayoutError("OpenDesign OCI rootfs must be a real directory")
    try:
        with tarfile.open(layer_path, mode="r:gz") as archive:
            for member in archive:
                relative = _member_path(member.name)
                if _apply_whiteout(rootfs, relative):
                    continue
                _apply_member(archive, rootfs, relative, member)
    except (OSError, tarfile.TarError) as exc:
        raise OciLayoutError("OpenDesign OCI layer is truncated or invalid") from exc


def _apply_member(
    archive: tarfile.TarFile,
    rootfs: Path,
    relative: PurePosixPath,
    member: tarfile.TarInfo,
) -> None:
    destination = rootfs.joinpath(*relative.parts)
    _prepare_parent(rootfs, destination.parent)
    if member.isdir():
        if destination.exists() or destination.is_symlink():
            mode = destination.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                _remove_entry(destination)
                destination.mkdir(mode=0o755)
        else:
            destination.mkdir(mode=0o755)
        destination.chmod(_normalized_mode(member.mode, directory=True))
        return
    if member.isreg():
        _remove_entry(destination)
        source = archive.extractfile(member)
        if source is None:
            raise OciLayoutError("OpenDesign OCI regular file has no payload")
        _write_regular_file(destination, source, _normalized_mode(member.mode, directory=False))
        return
    if member.issym():
        _remove_entry(destination)
        target = _safe_symlink_target(relative, member.linkname)
        destination.symlink_to(target)
        return
    if member.islnk():
        _remove_entry(destination)
        target_relative = _member_path(member.linkname)
        target = rootfs.joinpath(*target_relative.parts)
        _assert_existing_regular(rootfs, target)
        os.link(target, destination, follow_symlinks=False)
        return
    if member.isdev() or member.isfifo() or member.type in {tarfile.CHRTYPE, tarfile.BLKTYPE}:
        raise OciLayoutError("OpenDesign OCI special filesystem object is forbidden")
    raise OciLayoutError("OpenDesign OCI layer contains an unsupported filesystem object")


def _apply_whiteout(rootfs: Path, relative: PurePosixPath) -> bool:
    name = relative.name
    if not name.startswith(".wh."):
        return False
    parent = rootfs.joinpath(*relative.parent.parts)
    _prepare_parent(rootfs, parent)
    if name == ".wh..wh..opq":
        if parent.is_symlink() or not parent.is_dir():
            raise OciLayoutError("OpenDesign OCI opaque whiteout parent is unsafe")
        for child in list(parent.iterdir()):
            _remove_entry(child)
        return True
    target_name = name[4:]
    if not target_name or target_name in {".", ".."} or "/" in target_name or "\\" in target_name:
        raise OciLayoutError("OpenDesign OCI whiteout target is unsafe")
    _remove_entry(parent / target_name)
    return True


def _member_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise OciLayoutError("OpenDesign OCI archive path is unsafe")
    while value.startswith("./"):
        value = value[2:]
    value = value.rstrip("/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise OciLayoutError("OpenDesign OCI archive path is unsafe")
    return path


def _prepare_parent(rootfs: Path, parent: Path) -> None:
    try:
        relative = parent.relative_to(rootfs)
    except ValueError as exc:
        raise OciLayoutError("OpenDesign OCI archive parent escapes rootfs") from exc
    current = rootfs
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            current.mkdir(mode=0o755)
            continue
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise OciLayoutError("OpenDesign OCI archive path traverses a non-directory")


def _safe_symlink_target(relative: PurePosixPath, raw_target: str) -> str:
    if not isinstance(raw_target, str) or not raw_target or "\\" in raw_target or "\x00" in raw_target:
        raise OciLayoutError("OpenDesign OCI symlink target is unsafe")
    target = PurePosixPath(raw_target)
    if target.is_absolute():
        logical = PurePosixPath(*target.parts[1:])
    else:
        logical = relative.parent / target
    stack: list[str] = []
    for part in logical.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not stack:
                raise OciLayoutError("OpenDesign OCI symlink target escapes rootfs")
            stack.pop()
        else:
            stack.append(part)
    if not stack:
        raise OciLayoutError("OpenDesign OCI symlink target is empty")
    normalized = PurePosixPath(*stack)
    return os.path.relpath(normalized.as_posix(), relative.parent.as_posix() or ".").replace(os.sep, "/")


def _assert_existing_regular(rootfs: Path, target: Path) -> None:
    try:
        target.relative_to(rootfs)
        mode = target.lstat().st_mode
    except (ValueError, FileNotFoundError) as exc:
        raise OciLayoutError("OpenDesign OCI hardlink target is missing or unsafe") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise OciLayoutError("OpenDesign OCI hardlink target must be a real file")


def _write_regular_file(destination: Path, source: BinaryIO, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(destination, flags, mode)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            shutil.copyfileobj(source, handle, length=1024 * 1024)
            handle.flush()
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def _remove_entry(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def _normalized_mode(mode: int, *, directory: bool) -> int:
    executable = bool(mode & 0o111)
    if directory:
        return 0o755
    return 0o755 if executable else 0o644


__all__ = ["OciLayoutError", "apply_layer", "apply_layers"]
