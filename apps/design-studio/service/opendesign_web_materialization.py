"""Atomic publication of verified immutable OpenDesign web overlays."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
from uuid import uuid4

from opendesign_web_overlay import (
    VerifiedWebOverlay,
    WebOverlayError,
    verify_staged_web_overlay,
    verify_web_overlay,
)


def publish_web_overlay(
    source: Path,
    *,
    registry_root: Path,
    expected_digest: str,
    trust_contract: Path,
) -> tuple[VerifiedWebOverlay, bool]:
    """Verify and publish one overlay; return `(overlay, cache_hit)`."""
    registry = _registry_directory(registry_root)
    destination = registry / expected_digest
    if destination.exists() or destination.is_symlink():
        return (
            verify_web_overlay(
                destination,
                expected_digest=expected_digest,
                registry_root=registry,
                trust_contract=trust_contract,
            ),
            True,
        )
    source = _real_directory(source, label="web overlay publication source")
    staging = registry / f".{expected_digest}.{uuid4().hex}.staging"
    try:
        shutil.copytree(source, staging, symlinks=False)
        verify_staged_web_overlay(
            staging,
            expected_digest=expected_digest,
            registry_root=registry,
            trust_contract=trust_contract,
        )
        _make_immutable(staging)
        os.rename(staging, destination)
        _fsync_directory(registry)
        published = verify_web_overlay(
            destination,
            expected_digest=expected_digest,
            registry_root=registry,
            trust_contract=trust_contract,
        )
        return published, False
    except (OSError, WebOverlayError) as exc:
        raise WebOverlayError("OpenDesign web overlay publication failed closed") from exc
    finally:
        if staging.exists() and not staging.is_symlink():
            _make_writable(staging)
            shutil.rmtree(staging)


def _registry_directory(path: Path) -> Path:
    path = Path(path)
    if path.exists() or path.is_symlink():
        return _real_directory(path, label="web overlay registry")
    path.mkdir(parents=True, mode=0o755)
    return _real_directory(path, label="web overlay registry")


def _real_directory(path: Path, *, label: str) -> Path:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise WebOverlayError(f"{label} is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise WebOverlayError(f"{label} must be a real directory")
    return path.resolve(strict=True)


def _make_immutable(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def _make_writable(root: Path) -> None:
    for path in root.rglob("*"):
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() else 0o644)
    root.chmod(0o755)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
