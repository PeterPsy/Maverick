"""Owned filesystem operations for controlled OpenDesign migrations."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
from typing import Iterator, Mapping

from opendesign_migration_runtime import MigrationError


CONTROLLED_COPY_MARKER = "controlled-copy.json"
MAX_ATOMIC_JSON_BYTES = 16 * 1024 * 1024
GENERATION_ID = re.compile(r"^gen_[0-9A-Za-z][0-9A-Za-z._-]{0,79}$")
MIGRATION_ID = re.compile(r"^migration_[0-9A-Za-z][0-9A-Za-z._-]{0,79}$")
_CONTROLLED_COPY_PAYLOAD = {"schema_version": "1", "scope": "fixture-or-controlled-copy"}


def mark_controlled_copy(root: Path) -> None:
    """Authorize only a new fixture/copy root with empty structural directories."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise MigrationError("controlled-copy root must be a real directory")
    allowed = {"instances", "backups", "migrations"}
    children = {child.name for child in root.iterdir()}
    if not children.issubset(allowed):
        raise MigrationError("controlled-copy root contains unowned content")
    for name in allowed:
        directory = root / name
        if not directory.exists():
            directory.mkdir(mode=0o700)
        require_real_directory(directory, root=root, label=name)
        if any(directory.iterdir()):
            raise MigrationError(f"controlled-copy {name} directory is not empty")
    atomic_write_json(root / CONTROLLED_COPY_MARKER, _CONTROLLED_COPY_PAYLOAD)


def controlled_root(root: Path) -> Path:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise MigrationError("OpenDesign controlled-copy root must be a real directory")
    root = root.resolve(strict=True)
    marker = root / CONTROLLED_COPY_MARKER
    raw = read_bounded_regular_file(marker, root=root, max_bytes=1024)
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationError("controlled-copy marker is invalid") from exc
    if payload != _CONTROLLED_COPY_PAYLOAD:
        raise MigrationError("controlled-copy marker is not authorized")
    for child in ("instances", "backups", "migrations"):
        require_real_directory(root / child, root=root, label=child)
    return root


@contextmanager
def migration_lock(root: Path) -> Iterator[None]:
    lock_path = root / "migration.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise MigrationError("migration lock must be a regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MigrationError("another Design Studio migration holds the lock") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def create_snapshot(
    root: Path,
    migration_id: str,
    source_data: Path,
    legacy_state_path: Path | None,
    *,
    maximum_legacy_state_bytes: int,
) -> Path:
    validate_identifier(migration_id, MIGRATION_ID, "migration_id")
    destination = root / "backups" / migration_id
    if destination.exists() or destination.is_symlink():
        raise MigrationError("migration snapshot already exists")
    destination.mkdir(mode=0o700)
    try:
        copy_verified_tree(source_data, destination / "data")
        if legacy_state_path is not None:
            state_bytes = read_bounded_regular_file(
                legacy_state_path,
                root=root.parent,
                max_bytes=maximum_legacy_state_bytes,
            )
            state_path = destination / "legacy-state.json"
            state_path.write_bytes(state_bytes)
            state_path.chmod(0o600)
        fsync_tree(destination)
    except Exception:
        remove_owned_directory(destination, parent=root / "backups", label="incomplete migration snapshot")
        raise
    return destination


def clone_generation(root: Path, source_data: Path, generation_id: str) -> Path:
    validate_identifier(generation_id, GENERATION_ID, "target data generation")
    generation = root / "instances" / generation_id
    if generation.exists() or generation.is_symlink():
        raise MigrationError("target generation already exists")
    generation.mkdir(mode=0o700)
    target_data = generation / "data"
    try:
        copy_verified_tree(source_data, target_data)
        fsync_tree(generation)
    except Exception:
        remove_owned_directory(generation, parent=root / "instances", label="incomplete staging generation")
        raise
    return target_data


def copy_verified_tree(source: Path, destination: Path) -> None:
    source_digest = tree_sha256(source)
    shutil.copytree(source, destination, symlinks=False)
    if tree_sha256(destination) != source_digest:
        raise MigrationError("controlled tree copy digest mismatch")


def verify_free_space(root: Path, source_data: Path, *, minimum_free_bytes: int) -> None:
    source_size = sum(path.stat().st_size for path in source_data.rglob("*") if path.is_file())
    required = source_size * 2 + max(0, minimum_free_bytes)
    if shutil.disk_usage(root).free < required:
        raise MigrationError("insufficient free space for snapshot and staging")


def read_bounded_regular_file(path: Path, *, root: Path, max_bytes: int) -> bytes:
    path = Path(path)
    try:
        mode = path.lstat().st_mode
        resolved = path.resolve(strict=True)
        resolved.relative_to(Path(root).resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise MigrationError("controlled input escapes its app data root") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise MigrationError("controlled input must be a real regular file")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_bytes:
            raise MigrationError("controlled input exceeds its size limit")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            content = handle.read(max_bytes + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(content) > max_bytes:
        raise MigrationError("controlled input exceeds its size limit")
    return content


def require_real_directory(path: Path, *, root: Path, label: str) -> Path:
    try:
        mode = path.lstat().st_mode
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise MigrationError(f"{label} is missing or escapes the controlled root") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise MigrationError(f"{label} must be a real directory")
    return resolved


def remove_owned_directory(path: Path, *, parent: Path, label: str) -> None:
    parent = require_real_directory(parent, root=parent, label=f"{label} parent")
    path = require_real_directory(path, root=parent, label=label)
    if path.parent != parent:
        raise MigrationError(f"{label} is not a direct owned child")
    shutil.rmtree(path)
    fsync_directory(parent)


def clean_unjournaled_failure(
    root: Path,
    generation: Path | None,
    snapshot: Path | None,
    mapping: Path | None,
) -> None:
    if mapping is not None and mapping.is_file() and not mapping.is_symlink():
        mapping.unlink()
        fsync_directory(root)
    if generation is not None and generation.exists():
        remove_owned_directory(generation, parent=root / "instances", label="failed staging generation")
    if snapshot is not None and snapshot.exists():
        remove_owned_directory(snapshot, parent=root / "backups", label="failed migration snapshot")


def validate_identifier(value: str, pattern: re.Pattern[str], label: str) -> None:
    if not pattern.fullmatch(value):
        raise MigrationError(f"{label} is invalid")


def atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise MigrationError("atomic JSON destination must be a regular file")
    encoded = canonical_json(payload) + b"\n"
    if len(encoded) > MAX_ATOMIC_JSON_BYTES:
        raise MigrationError("atomic JSON payload exceeds its size limit")
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def canonical_json(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def tree_sha256(root: Path) -> str:
    require_real_directory(root, root=root, label="controlled tree")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise MigrationError("controlled tree contains a symlink")
        if stat.S_ISDIR(mode):
            digest.update(f"d:{relative}\n".encode("utf-8"))
        elif stat.S_ISREG(mode):
            digest.update(f"f:{relative}:{path.stat().st_size}:".encode("utf-8"))
            digest.update(bytes.fromhex(sha256_file(path)))
            digest.update(b"\n")
        else:
            raise MigrationError("controlled tree contains an unsupported file")
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def fsync_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
        elif path.is_dir() and not path.is_symlink():
            fsync_directory(path)
    fsync_directory(root)
    fsync_directory(root.parent)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MigrationError(f"duplicate JSON field: {key}")
        result[key] = value
    return result
