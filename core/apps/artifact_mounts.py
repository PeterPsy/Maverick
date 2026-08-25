"""Platform-owned read-only artifact namespaces for app sidecars."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
from typing import Iterable
from uuid import uuid4

from core.apps.errors import AppHostingError
from core.apps.models import HttpSidecarArtifactMountSpec


ARTIFACT_NAMESPACE_MARKER = ".maverick-artifact-namespace.json"
ARTIFACT_NAMESPACE_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class ResolvedArtifactMount:
    """One verified host namespace and its fixed sandbox target."""

    artifact_id: str
    source: Path
    target: Path
    store_generation: str


def platform_artifact_store_root(repository_root: Path) -> Path:
    """Resolve the installation-owned store root, always outside app source."""
    repository = Path(repository_root).resolve(strict=True)
    configured = os.environ.get("MAVERICK_APP_ARTIFACT_STORE_ROOT", "").strip()
    candidate = Path(configured) if configured else repository.parent / f".{repository.name}-app-artifacts"
    if not candidate.is_absolute():
        raise AppHostingError("MAVERICK_APP_ARTIFACT_STORE_ROOT must be an absolute path.")
    resolved = candidate.resolve(strict=False)
    if resolved == repository or repository in resolved.parents:
        raise AppHostingError("The platform app-artifact store must stay outside the repository source tree.")
    return resolved


def create_artifact_namespace(
    *,
    repository_root: Path,
    app_id: str,
    artifact_id: str,
) -> Path:
    """Create one platform-governed namespace before app materialization."""
    store_root = platform_artifact_store_root(repository_root)
    _mkdir_protected(store_root)
    app_root = store_root / app_id
    _mkdir_protected(app_root)
    namespace = app_root / artifact_id
    _mkdir_protected(namespace)
    marker_path = namespace / ARTIFACT_NAMESPACE_MARKER
    if not marker_path.exists():
        payload = {
            "schema_version": ARTIFACT_NAMESPACE_SCHEMA_VERSION,
            "app_id": app_id,
            "artifact_id": artifact_id,
            "store_generation": uuid4().hex,
            "owner_uid": os.geteuid(),
            "owner_gid": os.getegid(),
        }
        _write_new_marker(marker_path, payload)
    _validate_namespace(namespace, app_id=app_id, artifact_id=artifact_id)
    return namespace


def resolve_artifact_mounts(
    *,
    repository_root: Path,
    app_id: str,
    declarations: Iterable[HttpSidecarArtifactMountSpec],
) -> tuple[ResolvedArtifactMount, ...]:
    """Resolve declared namespaces without creating or repairing them."""
    store_root = platform_artifact_store_root(repository_root)
    if not store_root.exists():
        if tuple(declarations):
            raise AppHostingError("The platform app-artifact store is unavailable.")
        return ()
    store = _real_protected_directory(store_root, label="platform app-artifact store")
    mounts: list[ResolvedArtifactMount] = []
    for declaration in declarations:
        namespace = store / app_id / declaration.artifact_id
        marker = _validate_namespace(
            namespace,
            app_id=app_id,
            artifact_id=declaration.artifact_id,
        )
        mounts.append(
            ResolvedArtifactMount(
                artifact_id=declaration.artifact_id,
                source=namespace,
                target=Path(declaration.mount_path),
                store_generation=str(marker["store_generation"]),
            )
        )
    return tuple(mounts)


def _validate_namespace(namespace: Path, *, app_id: str, artifact_id: str) -> dict[str, object]:
    root = _real_protected_directory(namespace, label="app artifact namespace")
    marker_path = root / ARTIFACT_NAMESPACE_MARKER
    try:
        marker_metadata = marker_path.lstat()
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AppHostingError("The app artifact namespace marker is unavailable or invalid.") from error
    expected_fields = {"schema_version", "app_id", "artifact_id", "store_generation", "owner_uid", "owner_gid"}
    generation = payload.get("store_generation") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or set(payload) != expected_fields
        or payload.get("schema_version") != ARTIFACT_NAMESPACE_SCHEMA_VERSION
        or payload.get("app_id") != app_id
        or payload.get("artifact_id") != artifact_id
        or not isinstance(generation, str)
        or len(generation) != 32
        or any(character not in "0123456789abcdef" for character in generation)
        or isinstance(payload.get("owner_uid"), bool)
        or not isinstance(payload.get("owner_uid"), int)
        or isinstance(payload.get("owner_gid"), bool)
        or not isinstance(payload.get("owner_gid"), int)
    ):
        raise AppHostingError("The app artifact namespace marker identity is invalid.")
    root_metadata = root.stat()
    if (
        stat.S_ISLNK(marker_metadata.st_mode)
        or not stat.S_ISREG(marker_metadata.st_mode)
        or marker_metadata.st_uid != payload["owner_uid"]
        or marker_metadata.st_gid != payload["owner_gid"]
        or root_metadata.st_uid != payload["owner_uid"]
        or root_metadata.st_gid != payload["owner_gid"]
        or marker_metadata.st_mode & 0o022
        or root_metadata.st_mode & 0o022
    ):
        raise AppHostingError("The app artifact namespace ownership or protection is invalid.")
    return payload


def _real_protected_directory(path: Path, *, label: str) -> Path:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise AppHostingError(f"The {label} is missing.") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o022:
        raise AppHostingError(f"The {label} must be a protected real directory.")
    return path.resolve(strict=True)


def _mkdir_protected(path: Path) -> None:
    path.mkdir(mode=0o750, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise AppHostingError("The platform app-artifact store contains an unsafe path.")
    path.chmod(0o750)


def _write_new_marker(path: Path, payload: dict[str, object]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o640)
    try:
        body = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        os.write(descriptor, body)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
