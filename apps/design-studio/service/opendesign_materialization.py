"""Atomic installation and discovery of verified OpenDesign bundles."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile

from opendesign_archive import (
    FILE_MANIFEST_PATH,
    MATERIALIZED_MARKER_PATH,
    MATERIALIZED_MARKER_SCHEMA_VERSION,
    read_materialized_marker,
    validated_archive_members,
    verify_file_manifest,
    verify_materialized_bundle,
)
from opendesign_artifact import ArtifactError, is_sha256, sha256_file, write_canonical_json


@dataclass(frozen=True)
class MaterializedBundle:
    artifact_sha256: str
    file_manifest_sha256: str
    opendesign_version: str
    upstream_commit: str
    path: Path


def materialize_archive(
    archive_path: Path,
    registry_root: Path,
    *,
    expected_artifact_sha256: str,
    expected_file_manifest_sha256: str,
    opendesign_version: str,
    upstream_commit: str,
) -> MaterializedBundle:
    """Extract one verified archive into its immutable digest directory."""
    _validate_pin_set(
        expected_artifact_sha256=expected_artifact_sha256,
        expected_file_manifest_sha256=expected_file_manifest_sha256,
        opendesign_version=opendesign_version,
        upstream_commit=upstream_commit,
    )
    archive_path = Path(archive_path)
    _require_regular_file(archive_path, label="OpenDesign archive")
    if sha256_file(archive_path) != expected_artifact_sha256:
        raise ArtifactError("OpenDesign archive digest does not match the pin")

    registry_root = _prepare_registry_root(Path(registry_root))
    destination = registry_root / expected_artifact_sha256
    if destination.exists() or destination.is_symlink():
        return _verify_existing(
            destination,
            expected_artifact_sha256=expected_artifact_sha256,
            expected_file_manifest_sha256=expected_file_manifest_sha256,
            opendesign_version=opendesign_version,
            upstream_commit=upstream_commit,
        )

    stage = Path(tempfile.mkdtemp(prefix=".materialize-", dir=registry_root))
    activated = False
    try:
        _extract_archive(archive_path, stage)
        manifest_path = stage / FILE_MANIFEST_PATH
        _require_regular_file(manifest_path, label="OpenDesign file manifest")
        if sha256_file(manifest_path) != expected_file_manifest_sha256:
            raise ArtifactError("OpenDesign file manifest digest does not match the pin")
        verify_file_manifest(stage)
        marker = {
            "schema_version": MATERIALIZED_MARKER_SCHEMA_VERSION,
            "artifact_sha256": expected_artifact_sha256,
            "file_manifest_sha256": expected_file_manifest_sha256,
            "opendesign_version": opendesign_version,
            "upstream_commit": upstream_commit,
        }
        write_canonical_json(stage / MATERIALIZED_MARKER_PATH, marker)
        verify_materialized_bundle(
            stage,
            expected_artifact_sha256=expected_artifact_sha256,
            expected_file_manifest_sha256=expected_file_manifest_sha256,
            expected_version=opendesign_version,
        )
        _fsync_tree(stage)
        try:
            os.replace(stage, destination)
        except OSError as exc:
            raise ArtifactError("OpenDesign bundle activation failed") from exc
        activated = True
        _fsync_directory(registry_root)
    finally:
        if not activated and stage.exists():
            _remove_owned_stage(stage, registry_root)

    return MaterializedBundle(
        expected_artifact_sha256,
        expected_file_manifest_sha256,
        opendesign_version,
        upstream_commit,
        destination,
    )


def discover_verified_bundles(
    registry_root: Path,
    *,
    required_digests: set[str] | None = None,
) -> dict[str, MaterializedBundle]:
    """Return requested immutable bundles after full file verification.

    Normal launchers should pass the exact digests that can execute during that
    launch. Historical rollback bundles remain immutable registry entries, but
    their complete closures are reverified only when an operation selects them.
    Callers that omit ``required_digests`` retain the exhaustive audit behavior.
    """
    registry_root = _require_real_directory(Path(registry_root), label="OpenDesign bundle registry")
    requested = None if required_digests is None else set(required_digests)
    if requested is not None:
        if not requested or any(not is_sha256(digest) for digest in requested):
            raise ArtifactError("Requested OpenDesign bundle digests are invalid")
    bundles: dict[str, MaterializedBundle] = {}
    for candidate in sorted(registry_root.iterdir(), key=lambda item: item.name):
        if candidate.name.startswith("."):
            continue
        if not is_sha256(candidate.name):
            raise ArtifactError(f"Unexpected OpenDesign bundle registry entry: {candidate.name}")
        _require_real_directory(candidate, label="OpenDesign bundle registry entry")
        if requested is not None and candidate.name not in requested:
            continue
        marker = read_materialized_marker(candidate)
        if marker["artifact_sha256"] != candidate.name:
            raise ArtifactError("OpenDesign bundle registry directory does not match its marker")
        verify_materialized_bundle(
            candidate,
            expected_artifact_sha256=candidate.name,
            expected_file_manifest_sha256=marker["file_manifest_sha256"],
            expected_version=marker["opendesign_version"],
        )
        bundles[candidate.name] = MaterializedBundle(
            candidate.name,
            marker["file_manifest_sha256"],
            marker["opendesign_version"],
            marker["upstream_commit"],
            candidate,
        )
    if requested is not None and set(bundles) != requested:
        raise ArtifactError("A requested OpenDesign artifact is not materialized")
    if not bundles:
        raise ArtifactError("OpenDesign bundle registry contains no verified artifacts")
    return bundles


def _verify_existing(
    destination: Path,
    *,
    expected_artifact_sha256: str,
    expected_file_manifest_sha256: str,
    opendesign_version: str,
    upstream_commit: str,
) -> MaterializedBundle:
    try:
        marker = verify_materialized_bundle(
            destination,
            expected_artifact_sha256=expected_artifact_sha256,
            expected_file_manifest_sha256=expected_file_manifest_sha256,
            expected_version=opendesign_version,
        )
    except ArtifactError as exc:
        raise ArtifactError("Existing OpenDesign digest directory is invalid and was not replaced") from exc
    if marker["upstream_commit"] != upstream_commit:
        raise ArtifactError("Existing OpenDesign digest directory has the wrong upstream commit")
    return MaterializedBundle(
        expected_artifact_sha256,
        expected_file_manifest_sha256,
        opendesign_version,
        upstream_commit,
        destination,
    )


def _extract_archive(archive_path: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive_path, mode="r:gz") as bundle:
            members = validated_archive_members(bundle)
            bundle.extractall(destination, members=members, filter="data")
    except (OSError, tarfile.TarError) as exc:
        raise ArtifactError("OpenDesign archive extraction failed") from exc


def _prepare_registry_root(registry_root: Path) -> Path:
    if registry_root.exists() or registry_root.is_symlink():
        return _require_real_directory(registry_root, label="OpenDesign bundle registry")
    registry_root.parent.mkdir(parents=True, exist_ok=True)
    _require_real_directory(registry_root.parent, label="OpenDesign bundle registry parent")
    registry_root.mkdir(mode=0o755)
    _fsync_directory(registry_root.parent)
    return registry_root.resolve(strict=True)


def _require_regular_file(path: Path, *, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise ArtifactError(f"{label} is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ArtifactError(f"{label} must be a real file")


def _require_real_directory(path: Path, *, label: str) -> Path:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise ArtifactError(f"{label} is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ArtifactError(f"{label} must be a real directory")
    return path.resolve(strict=True)


def _validate_pin_set(
    *,
    expected_artifact_sha256: str,
    expected_file_manifest_sha256: str,
    opendesign_version: str,
    upstream_commit: str,
) -> None:
    if not is_sha256(expected_artifact_sha256) or not is_sha256(expected_file_manifest_sha256):
        raise ArtifactError("OpenDesign materialization digests are invalid")
    if (
        not isinstance(opendesign_version, str)
        or not opendesign_version.strip()
        or opendesign_version.strip() != opendesign_version
    ):
        raise ArtifactError("OpenDesign materialization version is invalid")
    if (
        not isinstance(upstream_commit, str)
        or len(upstream_commit) != 40
        or upstream_commit.lower() != upstream_commit
        or any(character not in "0123456789abcdef" for character in upstream_commit)
    ):
        raise ArtifactError("OpenDesign materialization commit is invalid")


def _remove_owned_stage(stage: Path, registry_root: Path) -> None:
    if not stage.name.startswith(".materialize-") or stage.parent != registry_root:
        raise ArtifactError("Refusing to clean an unowned OpenDesign staging directory")
    _require_real_directory(stage, label="OpenDesign staging directory")
    shutil.rmtree(stage)


def _fsync_tree(root: Path) -> None:
    for current_root, directories, filenames in os.walk(root, topdown=False, followlinks=False):
        current = Path(current_root)
        for name in sorted(filenames):
            path = current / name
            if path.is_symlink():
                continue
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        for name in sorted(directories):
            path = current / name
            if not path.is_symlink():
                _fsync_directory(path)
        _fsync_directory(current)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
