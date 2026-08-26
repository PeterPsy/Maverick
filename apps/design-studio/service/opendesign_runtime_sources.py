"""Pinned runtime-source catalog for current and rollback materialization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import stat
from typing import Any

from opendesign_artifact import (
    ArtifactError,
    is_sha256,
    read_bundle_manifest,
    safe_relative_path,
    selected_asset,
    sha256_file,
    validate_bundle_manifest,
)
from opendesign_attestation import verify_artifact_set


SERVICE_ROOT = Path(__file__).resolve().parent
RUNTIME_SOURCE_CATALOG_PATH = SERVICE_ROOT / "opendesign_runtime_sources.json"
_CURRENT_MANIFEST_NAME = "opendesign_bundle.json"
_ROLLBACK_MANIFEST_NAME = "opendesign_bundle_rollback_0_16_1.json"


@dataclass(frozen=True)
class RuntimeArtifactSource:
    """One exact signed input capable of publishing a declared runtime digest."""

    role: str
    artifact_sha256: str
    manifest_path: Path
    manifest_sha256: str
    source_subdirectory: str
    verifier_profile: str
    manifest: dict[str, Any]

    def artifact_directory(self, artifact_root: Path) -> Path:
        root = Path(artifact_root)
        if root.is_symlink() or not root.is_dir():
            raise ArtifactError("OpenDesign runtime source root must be a real directory")
        resolved_root = root.resolve(strict=True)
        candidate = root if self.source_subdirectory == "." else root.joinpath(
            *PurePosixPath(self.source_subdirectory).parts
        )
        try:
            metadata = candidate.lstat()
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(resolved_root)
        except (OSError, ValueError) as error:
            raise ArtifactError("Pinned OpenDesign runtime source directory is unavailable") from error
        if candidate.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            raise ArtifactError("Pinned OpenDesign runtime source must be a real directory")
        return resolved

    def verify_artifact_directory(
        self,
        manifest: dict[str, Any],
        artifact_directory: Path,
    ) -> dict[str, Any]:
        if manifest != self.manifest:
            raise ArtifactError("OpenDesign runtime source manifest changed after catalog resolution")
        return verify_artifact_set(
            manifest,
            artifact_directory,
            verifier_profile=self.verifier_profile,
        )


@dataclass(frozen=True)
class RuntimeSourceCatalog:
    """Exact current/rollback source bindings, keyed by both role and digest."""

    catalog_sha256: str
    by_role: dict[str, RuntimeArtifactSource]
    by_digest: dict[str, RuntimeArtifactSource]

    def source_for_digest(self, digest: str) -> RuntimeArtifactSource | None:
        return self.by_digest.get(digest)


def load_runtime_source_catalog(
    path: Path = RUNTIME_SOURCE_CATALOG_PATH,
    *,
    service_root: Path = SERVICE_ROOT,
) -> RuntimeSourceCatalog:
    """Load and strictly bind both release roles to their signed source manifests."""
    service = Path(service_root).resolve(strict=True)
    catalog_path = _real_file_within(path, root=service, label="runtime source catalog")
    payload = read_bundle_manifest(catalog_path)
    if set(payload) != {"schema_version", "sources"} or payload.get("schema_version") != "1":
        raise ArtifactError("OpenDesign runtime source catalog schema is invalid")
    entries = payload.get("sources")
    if not isinstance(entries, list) or len(entries) != 2:
        raise ArtifactError("OpenDesign runtime source catalog must declare current and rollback")

    by_role: dict[str, RuntimeArtifactSource] = {}
    by_digest: dict[str, RuntimeArtifactSource] = {}
    for entry in entries:
        source = _load_source(entry, service_root=service)
        if source.role in by_role or source.artifact_sha256 in by_digest:
            raise ArtifactError("OpenDesign runtime source catalog contains duplicate bindings")
        by_role[source.role] = source
        by_digest[source.artifact_sha256] = source
    if set(by_role) != {"current", "rollback"}:
        raise ArtifactError("OpenDesign runtime source catalog roles are incomplete")
    if by_role["current"].verifier_profile != "current-v2":
        raise ArtifactError("OpenDesign current runtime verifier profile is invalid")
    if by_role["rollback"].verifier_profile != "transactional-v1":
        raise ArtifactError("OpenDesign rollback runtime verifier profile is invalid")
    if by_role["current"].manifest_path.name != _CURRENT_MANIFEST_NAME:
        raise ArtifactError("OpenDesign current runtime manifest binding is invalid")
    if by_role["rollback"].manifest_path.name != _ROLLBACK_MANIFEST_NAME:
        raise ArtifactError("OpenDesign rollback runtime manifest binding is invalid")
    return RuntimeSourceCatalog(
        catalog_sha256=sha256_file(catalog_path),
        by_role=by_role,
        by_digest=by_digest,
    )


def _load_source(entry: object, *, service_root: Path) -> RuntimeArtifactSource:
    expected = {
        "role",
        "artifact_sha256",
        "manifest",
        "manifest_sha256",
        "source_subdirectory",
        "verifier_profile",
    }
    if not isinstance(entry, dict) or set(entry) != expected:
        raise ArtifactError("OpenDesign runtime source entry schema is invalid")
    role = str(entry.get("role") or "")
    digest = str(entry.get("artifact_sha256") or "")
    manifest_digest = str(entry.get("manifest_sha256") or "")
    verifier_profile = str(entry.get("verifier_profile") or "")
    if role not in {"current", "rollback"} or not is_sha256(digest):
        raise ArtifactError("OpenDesign runtime source identity is invalid")
    if not is_sha256(manifest_digest) or verifier_profile not in {
        "current-v2",
        "transactional-v1",
    }:
        raise ArtifactError("OpenDesign runtime source verification binding is invalid")
    manifest_relative = safe_relative_path(str(entry.get("manifest") or ""))
    manifest_path = _real_file_within(
        service_root.joinpath(*PurePosixPath(manifest_relative).parts),
        root=service_root,
        label="runtime source manifest",
    )
    if sha256_file(manifest_path) != manifest_digest:
        raise ArtifactError("OpenDesign runtime source manifest digest is invalid")
    source_subdirectory = str(entry.get("source_subdirectory") or "")
    if source_subdirectory != ".":
        source_subdirectory = safe_relative_path(source_subdirectory)
    manifest = read_bundle_manifest(manifest_path)
    validate_bundle_manifest(
        manifest,
        require_artifact_digest=True,
        verifier_profile=verifier_profile,
    )
    asset = selected_asset(manifest, require_artifact_digest=True)
    if asset["sha256"] != digest:
        raise ArtifactError("OpenDesign runtime source digest differs from its manifest")
    if role == "current" and source_subdirectory != ".":
        raise ArtifactError("OpenDesign current runtime source directory is invalid")
    expected_rollback_directory = f"runtime/{digest}"
    if role == "rollback" and source_subdirectory != expected_rollback_directory:
        raise ArtifactError("OpenDesign rollback runtime source directory is invalid")
    return RuntimeArtifactSource(
        role=role,
        artifact_sha256=digest,
        manifest_path=manifest_path,
        manifest_sha256=manifest_digest,
        source_subdirectory=source_subdirectory,
        verifier_profile=verifier_profile,
        manifest=manifest,
    )


def _real_file_within(path: Path, *, root: Path, label: str) -> Path:
    candidate = Path(path)
    try:
        metadata = candidate.lstat()
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise ArtifactError(f"OpenDesign {label} is unavailable") from error
    if candidate.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ArtifactError(f"OpenDesign {label} must be a real file")
    return resolved
