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
ARTIFACT_NAMESPACE_SCHEMA_VERSION = "2"


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
    """Resolve a namespace provisioned by a distinct platform authority.

    App hooks deliberately cannot create artifact namespaces.  They execute as
    the ordinary Maverick service principal, while the namespace must be owned
    by the separately provisioned artifact-authority principal.  Installation
    code invokes :func:`provision_artifact_namespace` as that authority before
    any app lifecycle hook is allowed to materialize artifacts.
    """
    store_root = platform_artifact_store_root(repository_root)
    namespace = store_root / app_id / artifact_id
    _validate_namespace(
        namespace,
        repository_root=repository_root,
        app_id=app_id,
        artifact_id=artifact_id,
    )
    return namespace


def provision_artifact_namespace(
    *,
    repository_root: Path,
    app_id: str,
    artifact_id: str,
) -> Path:
    """Create one namespace while running as the artifact authority.

    The authority must be a different kernel principal from the owner of the
    editable repository.  This is an OS-enforced boundary, not a marker claim:
    every store ancestor and the marker are required to be owned by the caller.
    """
    repository = Path(repository_root).resolve(strict=True)
    repository_uid, repository_gid = _repository_identity(repository)
    authority_uid = os.geteuid()
    authority_gid = os.getegid()
    if authority_uid == repository_uid:
        raise AppHostingError(
            "The platform artifact authority must differ from the editable repository owner."
        )
    store_root = platform_artifact_store_root(repository)
    app_root = store_root / app_id
    namespace = app_root / artifact_id
    for path in (store_root, app_root, namespace):
        _mkdir_authority_owned(
            path,
            authority_uid=authority_uid,
            authority_gid=authority_gid,
        )
    marker_path = namespace / ARTIFACT_NAMESPACE_MARKER
    if not marker_path.exists():
        payload = {
            "schema_version": ARTIFACT_NAMESPACE_SCHEMA_VERSION,
            "app_id": app_id,
            "artifact_id": artifact_id,
            "store_generation": uuid4().hex,
            "owner_uid": authority_uid,
            "owner_gid": authority_gid,
            "repository_uid": repository_uid,
            "repository_gid": repository_gid,
        }
        _write_new_marker(marker_path, payload)
        marker_path.chmod(0o444)
    _validate_namespace(
        namespace,
        repository_root=repository,
        app_id=app_id,
        artifact_id=artifact_id,
    )
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
            repository_root=repository_root,
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


def _validate_namespace(
    namespace: Path,
    *,
    repository_root: Path,
    app_id: str,
    artifact_id: str,
) -> dict[str, object]:
    root = _real_protected_directory(namespace, label="app artifact namespace")
    marker_path = root / ARTIFACT_NAMESPACE_MARKER
    try:
        marker_metadata = marker_path.lstat()
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AppHostingError("The app artifact namespace marker is unavailable or invalid.") from error
    expected_fields = {
        "schema_version",
        "app_id",
        "artifact_id",
        "store_generation",
        "owner_uid",
        "owner_gid",
        "repository_uid",
        "repository_gid",
    }
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
        or isinstance(payload.get("repository_uid"), bool)
        or not isinstance(payload.get("repository_uid"), int)
        or isinstance(payload.get("repository_gid"), bool)
        or not isinstance(payload.get("repository_gid"), int)
    ):
        raise AppHostingError("The app artifact namespace marker identity is invalid.")
    repository = Path(repository_root).resolve(strict=True)
    repository_uid, repository_gid = _repository_identity(repository)
    root_metadata = root.stat()
    store_root = platform_artifact_store_root(repository)
    app_root = store_root / app_id
    protected_ancestors = (
        _real_protected_directory(store_root, label="platform app-artifact store"),
        _real_protected_directory(app_root, label="app artifact store"),
    )
    if (
        stat.S_ISLNK(marker_metadata.st_mode)
        or not stat.S_ISREG(marker_metadata.st_mode)
        or marker_metadata.st_uid != payload["owner_uid"]
        or marker_metadata.st_gid != payload["owner_gid"]
        or root_metadata.st_uid != payload["owner_uid"]
        or root_metadata.st_gid != payload["owner_gid"]
        or marker_metadata.st_mode & 0o222
        or root_metadata.st_mode & 0o022
        or repository_uid != payload["repository_uid"]
        or repository_gid != payload["repository_gid"]
        or payload["owner_uid"] == payload["repository_uid"]
        or any(
            path.stat().st_uid != payload["owner_uid"]
            or path.stat().st_gid != payload["owner_gid"]
            or path.stat().st_mode & 0o022
            for path in protected_ancestors
        )
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


def _repository_identity(repository: Path) -> tuple[int, int]:
    metadata = repository.stat()
    return metadata.st_uid, metadata.st_gid


def _mkdir_authority_owned(path: Path, *, authority_uid: int, authority_gid: int) -> None:
    path.mkdir(mode=0o755, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise AppHostingError("The platform app-artifact store contains an unsafe path.")
    metadata = path.stat()
    if metadata.st_uid != authority_uid or metadata.st_gid != authority_gid:
        raise AppHostingError("The platform app-artifact store is not owned by its authority.")
    # Artifact closures are not secrets.  Read/execute access lets the ordinary
    # service principal validate and mount them while only the authority owner
    # can ever mutate the namespace.
    path.chmod(0o755)


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
