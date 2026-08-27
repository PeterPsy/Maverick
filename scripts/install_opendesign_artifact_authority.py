#!/usr/bin/env python3
"""Install the root-protected OpenDesign artifact authority boundary.

This script is invoked by the Maverick installer as root.  It snapshots the
small verification TCB away from the editable checkout, creates a dedicated
non-login principal, and installs the only sudo command that the Maverick
service principal may use for artifact maintenance.
"""

from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import tempfile
from typing import BinaryIO


ACCOUNT_NAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
EXCLUDED_DIRECTORIES = frozenset(
    {"__pycache__", ".pytest_cache", "artifacts", "node_modules", "vendor"}
)
EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo"})
DEFAULT_AUTHORITY_USER = "maverick-artifacts"
DEFAULT_AUTHORITY_GROUP = "maverick-artifacts"
DEFAULT_STORE_ROOT = Path("/var/lib/maverick/app-artifacts")
DEFAULT_SNAPSHOT_ROOT = Path("/usr/lib/maverick/opendesign-artifact-authority")
DEFAULT_COMMAND_PATH = Path("/usr/local/libexec/maverick-opendesign-artifact-authority")
DEFAULT_CONFIG_PATH = Path("/etc/maverick/opendesign-artifact-authority.json")
DEFAULT_SUDOERS_PATH = Path("/etc/sudoers.d/maverick-opendesign-artifact-authority")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--service-user", required=True)
    parser.add_argument("--authority-user", default=DEFAULT_AUTHORITY_USER)
    parser.add_argument("--authority-group", default=DEFAULT_AUTHORITY_GROUP)
    parser.add_argument("--store-root", type=Path, default=DEFAULT_STORE_ROOT)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--command-path", type=Path, default=DEFAULT_COMMAND_PATH)
    parser.add_argument("--config-path", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--sudoers-path", type=Path, default=DEFAULT_SUDOERS_PATH)
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise SystemExit("OpenDesign artifact authority installation requires root")

    repository = args.repository_root.resolve(strict=True)
    _validate_account_name(args.service_user, label="service user")
    _validate_account_name(args.authority_user, label="authority user")
    _validate_account_name(args.authority_group, label="authority group")
    service = pwd.getpwnam(args.service_user)
    authority = _ensure_authority_account(args.authority_user, args.authority_group)
    if authority.pw_uid == 0 or authority.pw_uid == repository.stat().st_uid:
        raise RuntimeError("artifact authority must differ from root and the repository owner")

    store_root = _absolute_outside_repository(args.store_root, repository, label="store")
    snapshot_root = _absolute_outside_repository(args.snapshot_root, repository, label="snapshot")
    command_path = _absolute_outside_repository(args.command_path, repository, label="command")
    config_path = _absolute_outside_repository(args.config_path, repository, label="config")
    sudoers_path = _absolute_outside_repository(args.sudoers_path, repository, label="sudoers")
    source_root = repository / "apps/design-studio/service/artifacts"

    module_root = _install_module_snapshot(repository, snapshot_root)
    launcher_source = repository / "scripts/opendesign_artifact_authority.py"
    _install_regular_file(launcher_source, command_path, mode=0o755)
    config = {
        "schema_version": "1",
        "authority_user": args.authority_user,
        "authority_group": args.authority_group,
        "module_root": str(module_root),
        "repository_root": str(repository),
        "artifact_store_root": str(store_root),
        "artifact_source_root": str(source_root),
    }
    _install_bytes(
        config_path,
        (json.dumps(config, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
        mode=0o444,
    )
    _prepare_store_root(store_root, uid=authority.pw_uid, gid=authority.pw_gid)

    # In sudoers, an explicit empty argument string means this command may only
    # be invoked without argv.  Its small JSON request is validated on stdin.
    sudoers = f'{service.pw_name} ALL=(root) NOPASSWD: {command_path} ""\n'.encode("utf-8")
    _install_sudoers(sudoers_path, sudoers)
    return 0


def _validate_account_name(value: str, *, label: str) -> None:
    if ACCOUNT_NAME.fullmatch(value) is None:
        raise RuntimeError(f"invalid {label}")


def _ensure_authority_account(user_name: str, group_name: str) -> pwd.struct_passwd:
    try:
        group = grp.getgrnam(group_name)
    except KeyError:
        subprocess.run(["groupadd", "--system", group_name], check=True)
        group = grp.getgrnam(group_name)
    try:
        account = pwd.getpwnam(user_name)
    except KeyError:
        nologin = shutil.which("nologin") or "/usr/sbin/nologin"
        subprocess.run(
            [
                "useradd",
                "--system",
                "--gid",
                group_name,
                "--home-dir",
                "/nonexistent",
                "--shell",
                nologin,
                "--no-create-home",
                user_name,
            ],
            check=True,
        )
        account = pwd.getpwnam(user_name)
    if account.pw_gid != group.gr_gid or account.pw_uid <= 0:
        raise RuntimeError("artifact authority account identity is invalid")
    if Path(account.pw_shell).name not in {"nologin", "false"}:
        raise RuntimeError("artifact authority account must have a non-login shell")
    return account


def _absolute_outside_repository(path: Path, repository: Path, *, label: str) -> Path:
    if not path.is_absolute():
        raise RuntimeError(f"artifact authority {label} path must be absolute")
    resolved = path.resolve(strict=False)
    if resolved == repository or repository in resolved.parents:
        raise RuntimeError(f"artifact authority {label} path is inside the repository")
    return resolved


def _install_module_snapshot(repository: Path, snapshot_root: Path) -> Path:
    _ensure_root_directory(snapshot_root, mode=0o755)
    stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=snapshot_root))
    try:
        digest = hashlib.sha256()
        sources = (
            (repository / "core", stage / "core", Path("core")),
            (
                repository / "apps/design-studio/service",
                stage / "apps/design-studio/service",
                Path("apps/design-studio/service"),
            ),
        )
        for source, destination, relative in sources:
            _copy_tree_from_descriptor(source, destination, relative=relative, digest=digest)
        snapshot_digest = digest.hexdigest()
        destination = snapshot_root / snapshot_digest
        _seal_snapshot(stage)
        if destination.exists() or destination.is_symlink():
            _validate_existing_snapshot(destination, expected_digest=snapshot_digest)
            shutil.rmtree(stage)
        else:
            os.rename(stage, destination)
            _fsync_directory(snapshot_root)
        return destination
    except Exception:
        if stage.exists() and not stage.is_symlink():
            shutil.rmtree(stage)
        raise


def _copy_tree_from_descriptor(
    source: Path,
    destination: Path,
    *,
    relative: Path,
    digest: "hashlib._Hash",
) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    try:
        _copy_directory_contents(descriptor, destination, relative=relative, digest=digest)
    finally:
        os.close(descriptor)


def _copy_directory_contents(
    source_descriptor: int,
    destination: Path,
    *,
    relative: Path,
    digest: "hashlib._Hash",
) -> None:
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in sorted(os.listdir(source_descriptor)):
        if name in {".", ".."} or "/" in name or "\x00" in name:
            raise RuntimeError("unsafe artifact authority snapshot entry")
        metadata = os.stat(name, dir_fd=source_descriptor, follow_symlinks=False)
        child_relative = relative / name
        if stat.S_ISDIR(metadata.st_mode):
            if name in EXCLUDED_DIRECTORIES:
                continue
            child_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            child_descriptor = os.open(name, child_flags, dir_fd=source_descriptor)
            try:
                _copy_directory_contents(
                    child_descriptor,
                    destination / name,
                    relative=child_relative,
                    digest=digest,
                )
            finally:
                os.close(child_descriptor)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("artifact authority snapshot source contains a non-regular entry")
        if Path(name).suffix in EXCLUDED_SUFFIXES:
            continue
        source_file = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=source_descriptor,
        )
        try:
            observed = os.fstat(source_file)
            if not stat.S_ISREG(observed.st_mode) or (observed.st_dev, observed.st_ino) != (
                metadata.st_dev,
                metadata.st_ino,
            ):
                raise RuntimeError("artifact authority snapshot source changed during copy")
            file_digest = hashlib.sha256()
            output_path = destination / name
            with output_path.open("xb") as output:
                _copy_and_hash(source_file, output, file_digest=file_digest)
                output.flush()
                os.fsync(output.fileno())
            digest.update(b"F\0")
            digest.update(child_relative.as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(file_digest.digest())
        finally:
            os.close(source_file)


def _copy_and_hash(source_descriptor: int, output: BinaryIO, *, file_digest: "hashlib._Hash") -> None:
    while True:
        chunk = os.read(source_descriptor, 1024 * 1024)
        if not chunk:
            break
        output.write(chunk)
        file_digest.update(chunk)


def _seal_snapshot(root: Path) -> None:
    directories: list[Path] = []
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeError("artifact authority snapshot contains a symlink")
        os.chown(path, 0, 0, follow_symlinks=False)
        path.chmod(0o555 if stat.S_ISDIR(metadata.st_mode) else 0o444)
        if stat.S_ISDIR(metadata.st_mode):
            directories.append(path)
    os.chown(root, 0, 0)
    root.chmod(0o555)
    for directory in directories:
        _fsync_directory(directory)
    _fsync_directory(root)


def _validate_existing_snapshot(root: Path, *, expected_digest: str) -> None:
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError("artifact authority snapshot destination is unsafe")
    digest = hashlib.sha256()
    for path in (root, *sorted(root.rglob("*"))):
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or metadata.st_mode & 0o222
        ):
            raise RuntimeError("artifact authority snapshot destination is not sealed")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("artifact authority snapshot destination is unsafe")
        digest.update(b"F\0")
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    if digest.hexdigest() != expected_digest:
        raise RuntimeError("artifact authority snapshot destination digest differs")


def _install_regular_file(source: Path, destination: Path, *, mode: int) -> None:
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("artifact authority launcher source is not a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    _install_bytes(destination, b"".join(chunks), mode=mode)


def _install_bytes(destination: Path, content: bytes, *, mode: int) -> None:
    _ensure_root_directory(destination.parent, mode=0o755)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chown(temporary_path, 0, 0)
        temporary_path.chmod(mode)
        os.replace(temporary_path, destination)
        _fsync_directory(destination.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def _prepare_store_root(path: Path, *, uid: int, gid: int) -> None:
    _ensure_root_directory(path.parent, mode=0o755)
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError("artifact store root is unsafe")
        if metadata.st_uid not in {0, uid} or any(path.iterdir()):
            if metadata.st_uid != uid or metadata.st_gid != gid:
                raise RuntimeError("existing artifact store root has an unexpected owner")
    else:
        path.mkdir(mode=0o755)
    os.chown(path, uid, gid)
    path.chmod(0o755)
    _fsync_directory(path.parent)


def _install_sudoers(path: Path, content: bytes) -> None:
    _ensure_root_directory(path.parent, mode=0o755)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chown(temporary_path, 0, 0)
        temporary_path.chmod(0o440)
        visudo = shutil.which("visudo") or "/usr/sbin/visudo"
        subprocess.run([visudo, "-cf", str(temporary_path)], check=True)
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def _ensure_root_directory(path: Path, *, mode: int) -> None:
    path.mkdir(mode=mode, parents=True, exist_ok=True)
    resolved = path.resolve(strict=True)
    for candidate in (resolved, *resolved.parents):
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError("artifact authority destination contains an unsafe directory")
        if candidate == Path("/"):
            break
        if metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise RuntimeError("artifact authority destination is not root-protected")
    path.chmod(mode)
    os.chown(path, 0, 0)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    raise SystemExit(main())
