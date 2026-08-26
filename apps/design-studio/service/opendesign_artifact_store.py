"""Protected content-addressed store, receipts, audit, and atomic repair."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time
from typing import Any, Callable, Iterator
from uuid import uuid4

from opendesign_archive import FILE_MANIFEST_PATH, read_materialized_marker
from opendesign_artifact import (
    ArtifactError,
    is_sha256,
    sha256_file,
    write_canonical_json,
)
from opendesign_attestation import verify_artifact_set
from opendesign_materialization import materialize_archive
from opendesign_store_manifest import (
    StoreManifestError,
    create_store_manifest,
    manifest_sha256,
    validate_store_manifest,
    verify_store_manifest,
)
from opendesign_web_materialization import publish_web_overlay
from opendesign_web_overlay import VerifiedWebOverlay, verify_staged_web_overlay


NAMESPACE_MARKER = ".maverick-artifact-namespace.json"
RECEIPT_SCHEMA_VERSION = "1"
VERIFIER_VERSION = "opendesign-store-v1"
FailureInjector = Callable[[str], None]


class ArtifactStoreError(ArtifactError):
    """Typed, redaction-safe artifact-store failure."""

    def __init__(self, code: str, phase: str, message: str, *, differences: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.phase = phase
        self.differences = max(0, differences)


@dataclass(frozen=True)
class StoredArtifact:
    kind: str
    artifact_sha256: str
    content_path: Path
    package_path: Path
    receipt: dict[str, Any]


class OpenDesignArtifactStore:
    """Own OpenDesign runtime and web generations outside the source tree."""

    def __init__(self, namespace_root: Path, *, require_read_only_mount: bool = False) -> None:
        self.root = _real_directory(namespace_root, label="OpenDesign artifact namespace")
        self.require_read_only_mount = require_read_only_mount
        self.namespace = self._namespace_marker()
        self._ensure_layout(create=not require_read_only_mount)

    @property
    def store_generation(self) -> str:
        return str(self.namespace["store_generation"])

    def package_identity(self, kind: str, digest: str) -> tuple[int, int] | None:
        """Return the stable active-directory identity used by audited repair handoff."""
        _validate_kind_digest(kind, digest)
        path = self.root / kind / digest
        if not path.exists() and not path.is_symlink():
            return None
        return _directory_identity(path)

    def publish_runtime(
        self,
        artifact_directory: Path,
        *,
        manifest: dict[str, Any],
        repair: bool = False,
        invalid_package_identity: tuple[int, int] | None = None,
        failure_injector: FailureInjector | None = None,
    ) -> StoredArtifact:
        """Materialize, fully audit, receipt, fsync, and atomically publish runtime."""
        try:
            asset = verify_artifact_set(manifest, artifact_directory)
            artifact_sha256 = str(asset["sha256"])
            file_manifest_sha256 = str(asset["file_manifest_sha256"])
            archive_path = artifact_directory / str(asset["file"])
            archive_identity_after = _regular_file_identity(archive_path)
            opendesign_version = str(manifest["upstream"]["release_version"])
            upstream_commit = str(manifest["upstream"]["commit"])
        except ArtifactError as error:
            raise ArtifactStoreError(
                "artifact_integrity_mismatch",
                "provenance_verify",
                "OpenDesign artifact set failed digest, signature, SBOM, license, or provenance verification",
            ) from error

        def build(content: Path) -> dict[str, Any]:
            temporary_registry = content.parent / "materialized"
            materialized = materialize_archive(
                archive_path,
                temporary_registry,
                expected_artifact_sha256=artifact_sha256,
                expected_file_manifest_sha256=file_manifest_sha256,
                opendesign_version=opendesign_version,
                upstream_commit=upstream_commit,
                fsync=False,
                verified_archive_identity=archive_identity_after,
            )
            os.rename(materialized.path, content)
            shutil.rmtree(temporary_registry)
            _inject(failure_injector, "extraction")
            return {
                "compatible_runtime_artifact_sha256": [artifact_sha256],
                "verified_file_manifest": _read_json(
                    content / FILE_MANIFEST_PATH,
                    label="verified OpenDesign runtime file manifest",
                ),
                "verified_directory_entries": list(materialized.verified_directory_entries),
            }

        return self._publish(
            "runtime",
            artifact_sha256,
            opendesign_version=opendesign_version,
            upstream_commit=upstream_commit,
            source_file_manifest_sha256=file_manifest_sha256,
            build=build,
            repair=repair,
            invalid_package_identity=invalid_package_identity,
            trust_contract=None,
            failure_injector=failure_injector,
        )

    def publish_web_overlay(
        self,
        source: Path,
        *,
        web_overlay_sha256: str,
        trust_contract: Path,
        repair: bool = False,
        invalid_package_identity: tuple[int, int] | None = None,
        failure_injector: FailureInjector | None = None,
    ) -> StoredArtifact:
        """Verify, normalize, fully audit, and atomically publish one web overlay."""
        overlay_holder: dict[str, VerifiedWebOverlay] = {}

        def build(content: Path) -> dict[str, Any]:
            temporary_registry = content.parent / "materialized"
            overlay, _cache_hit = publish_web_overlay(
                source,
                registry_root=temporary_registry,
                expected_digest=web_overlay_sha256,
                trust_contract=trust_contract,
            )
            overlay_holder["overlay"] = overlay
            shutil.copytree(overlay.path, content, symlinks=True)
            _make_owner_writable(temporary_registry)
            shutil.rmtree(temporary_registry)
            _inject(failure_injector, "extraction")
            return {
                "compatible_runtime_artifact_sha256": sorted(overlay.compatible_runtime_artifact_sha256),
                "source_file_manifest_sha256": overlay.file_manifest_sha256,
                "opendesign_version": overlay.od_version,
                "upstream_commit": overlay.upstream_commit,
            }

        result = self._publish(
            "web",
            web_overlay_sha256,
            opendesign_version="",
            upstream_commit="",
            source_file_manifest_sha256="",
            build=build,
            repair=repair,
            invalid_package_identity=invalid_package_identity,
            trust_contract=trust_contract,
            failure_injector=failure_injector,
        )
        return result

    def fast_runtime(
        self,
        artifact_sha256: str,
        *,
        file_manifest_sha256: str | None,
        opendesign_version: str,
        upstream_commit: str | None,
    ) -> StoredArtifact:
        return self._fast(
            "runtime",
            artifact_sha256,
            source_file_manifest_sha256=file_manifest_sha256,
            opendesign_version=opendesign_version,
            upstream_commit=upstream_commit,
        )

    def fast_web_overlay(self, digest: str, *, runtime_artifact_sha256: str) -> StoredArtifact:
        result = self._fast("web", digest)
        compatible = result.receipt.get("compatible_runtime_artifact_sha256")
        if not isinstance(compatible, list) or runtime_artifact_sha256 not in compatible:
            raise ArtifactStoreError(
                "runtime_binding_invalid",
                "artifact_fast_verify",
                "OpenDesign runtime and web overlay are incompatible",
            )
        return result

    def full_audit(
        self,
        kind: str,
        digest: str,
        *,
        trust_contract: Path | None = None,
        max_workers: int | None = None,
    ) -> StoredArtifact:
        result = self._fast(kind, digest, require_mount=False)
        manifest = _read_json(result.package_path / "manifest-v2.json", label="store manifest v2")
        try:
            if manifest_sha256(manifest) != result.receipt["file_manifest_sha256"]:
                raise ArtifactStoreError(
                    "artifact_integrity_mismatch",
                    "artifact_full_verify",
                    "OpenDesign store manifest v2 differs from its protected receipt",
                    differences=1,
                )
            verify_store_manifest(result.content_path, manifest, max_workers=max_workers)
            if kind == "runtime":
                marker = read_materialized_marker(result.content_path)
                if (
                    marker["artifact_sha256"] != digest
                    or marker["file_manifest_sha256"]
                    != result.receipt["source_file_manifest_sha256"]
                    or marker["opendesign_version"] != result.receipt["opendesign_version"]
                    or marker["upstream_commit"] != result.receipt["upstream_commit"]
                ):
                    raise ArtifactStoreError(
                        "artifact_integrity_mismatch",
                        "artifact_full_verify",
                        "OpenDesign runtime materialization identity differs from its receipt",
                        differences=1,
                    )
            elif kind == "web":
                if trust_contract is None:
                    raise ArtifactStoreError(
                        "runtime_binding_invalid",
                        "artifact_full_verify",
                        "OpenDesign web audit requires its trust contract",
                    )
                verify_staged_web_overlay(
                    result.content_path,
                    expected_digest=digest,
                    registry_root=result.package_path,
                    trust_contract=trust_contract,
                )
        except StoreManifestError as error:
            raise ArtifactStoreError(
                "artifact_integrity_mismatch",
                "artifact_full_verify",
                str(error),
                differences=error.differences,
            ) from error
        except ArtifactStoreError:
            raise
        except Exception as error:
            raise ArtifactStoreError(
                "artifact_integrity_mismatch",
                "artifact_full_verify",
                "OpenDesign protected store full audit failed",
                differences=1,
            ) from error
        return result

    def _publish(
        self,
        kind: str,
        digest: str,
        *,
        opendesign_version: str,
        upstream_commit: str,
        source_file_manifest_sha256: str,
        build: Callable[[Path], dict[str, Any]],
        repair: bool,
        invalid_package_identity: tuple[int, int] | None,
        trust_contract: Path | None,
        failure_injector: FailureInjector | None,
    ) -> StoredArtifact:
        _validate_kind_digest(kind, digest)
        destination = self.root / kind / digest
        with self._digest_lock(kind, digest):
            if destination.exists() or destination.is_symlink():
                current_identity = _directory_identity(destination)
                if not (repair and invalid_package_identity == current_identity):
                    try:
                        return self.full_audit(kind, digest, trust_contract=trust_contract)
                    except ArtifactStoreError:
                        if not repair:
                            raise
            stage = Path(tempfile.mkdtemp(prefix=f".{kind}-{digest[:12]}-", dir=self.root / ".staging"))
            activated = False
            try:
                content = stage / "content"
                extra = build(content)
                manifest = create_store_manifest(
                    content,
                    verified_file_manifest=extra.get("verified_file_manifest"),
                    verified_directory_entries=extra.get("verified_directory_entries"),
                )
                write_canonical_json(stage / "manifest-v2.json", manifest)
                validate_store_manifest(manifest)
                _inject(failure_injector, "full_verify")
                receipt = self._receipt(
                    kind,
                    digest,
                    manifest=manifest,
                    opendesign_version=opendesign_version or str(extra.get("opendesign_version") or "0.16.1"),
                    upstream_commit=upstream_commit or str(extra.get("upstream_commit") or ""),
                    source_file_manifest_sha256=(
                        source_file_manifest_sha256
                        or str(extra.get("source_file_manifest_sha256") or "")
                    ),
                    compatible_runtime_artifact_sha256=list(extra["compatible_runtime_artifact_sha256"]),
                )
                write_canonical_json(stage / "receipt.json", receipt)
                _inject(failure_injector, "receipt")
                _protect_package(stage, owner_uid=int(self.namespace["owner_uid"]), owner_gid=int(self.namespace["owner_gid"]))
                _fsync_tree(stage)
                _inject(failure_injector, "fsync")
                if destination.exists() or destination.is_symlink():
                    if not repair:
                        raise ArtifactStoreError(
                            "artifact_integrity_mismatch",
                            "publish",
                            "Existing OpenDesign store generation is invalid; governed repair is required",
                        )
                    quarantine = self.root / "quarantine" / kind / f"{digest}.{int(time.time())}.{uuid4().hex[:8]}"
                    os.rename(destination, quarantine)
                    _fsync_directory(quarantine.parent)
                    _inject(failure_injector, "quarantine")
                os.rename(stage, destination)
                activated = True
                _fsync_directory(destination.parent)
                _inject(failure_injector, "rename")
            finally:
                if not activated and stage.exists() and not stage.is_symlink():
                    _make_owner_writable(stage)
                    shutil.rmtree(stage)
            return self._fast(kind, digest, require_mount=False)

    def _fast(
        self,
        kind: str,
        digest: str,
        *,
        source_file_manifest_sha256: str | None = None,
        opendesign_version: str | None = None,
        upstream_commit: str | None = None,
        require_mount: bool | None = None,
    ) -> StoredArtifact:
        _validate_kind_digest(kind, digest)
        owner_uid = _mapped_namespace_id(int(self.namespace["owner_uid"]), Path("/proc/self/uid_map"))
        owner_gid = _mapped_namespace_id(int(self.namespace["owner_gid"]), Path("/proc/self/gid_map"))
        package = _real_directory(
            self.root / kind / digest,
            label="OpenDesign store package",
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
        if _audited_invalid_package(
            self.root,
            kind=kind,
            digest=digest,
            store_generation=self.store_generation,
            package_identity=_directory_identity(package),
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        ):
            raise ArtifactStoreError(
                "artifact_integrity_mismatch",
                "artifact_fast_verify",
                "OpenDesign artifact was rejected by a protected full-audit handoff",
                differences=1,
            )
        content = _real_directory(
            package / "content",
            label="OpenDesign store content",
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
        receipt = _read_json(
            package / "receipt.json",
            label="OpenDesign store receipt",
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
        _validate_receipt(receipt, kind=kind, digest=digest, store_generation=self.store_generation)
        if source_file_manifest_sha256 is not None and receipt["source_file_manifest_sha256"] != source_file_manifest_sha256:
            raise ArtifactStoreError("artifact_integrity_mismatch", "artifact_fast_verify", "OpenDesign source manifest pin differs")
        if opendesign_version is not None and receipt["opendesign_version"] != opendesign_version:
            raise ArtifactStoreError("runtime_binding_invalid", "artifact_fast_verify", "OpenDesign version binding differs")
        if upstream_commit is not None and receipt["upstream_commit"] != upstream_commit:
            raise ArtifactStoreError("runtime_binding_invalid", "artifact_fast_verify", "OpenDesign commit binding differs")
        manifest_path = package / "manifest-v2.json"
        _protected_file(
            manifest_path,
            label="OpenDesign store manifest v2",
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
        try:
            observed_manifest_sha256 = sha256_file(manifest_path)
        except (OSError, ArtifactError) as error:
            raise ArtifactStoreError(
                "artifact_integrity_mismatch",
                "artifact_fast_verify",
                "OpenDesign store manifest v2 cannot be authenticated",
            ) from error
        if observed_manifest_sha256 != receipt["file_manifest_sha256"]:
            raise ArtifactStoreError(
                "artifact_integrity_mismatch",
                "artifact_fast_verify",
                "OpenDesign store manifest v2 differs from its protected receipt",
                differences=1,
            )
        should_require_mount = self.require_read_only_mount if require_mount is None else require_mount
        if should_require_mount and not _path_is_read_only_mount(self.root):
            raise ArtifactStoreError(
                "artifact_permissions_invalid",
                "artifact_fast_verify",
                "OpenDesign artifact namespace is not mounted read-only",
            )
        return StoredArtifact(kind, digest, content, package, receipt)

    def _receipt(
        self,
        kind: str,
        digest: str,
        *,
        manifest: dict[str, Any],
        opendesign_version: str,
        upstream_commit: str,
        source_file_manifest_sha256: str,
        compatible_runtime_artifact_sha256: list[str],
    ) -> dict[str, Any]:
        return {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "kind": kind,
            "artifact_sha256": digest,
            "runtime_artifact_sha256": digest if kind == "runtime" else compatible_runtime_artifact_sha256[0],
            "file_manifest_sha256": manifest_sha256(manifest),
            "source_file_manifest_sha256": source_file_manifest_sha256,
            "upstream_commit": upstream_commit,
            "opendesign_version": opendesign_version,
            "file_count": manifest["file_count"],
            "total_size_bytes": manifest["total_size_bytes"],
            "verifier_version": VERIFIER_VERSION,
            "store_generation": self.store_generation,
            "verified_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
            "compatible_runtime_artifact_sha256": compatible_runtime_artifact_sha256,
        }

    def _namespace_marker(self) -> dict[str, Any]:
        marker = _read_json(self.root / NAMESPACE_MARKER, label="artifact namespace marker")
        expected = {"schema_version", "app_id", "artifact_id", "store_generation", "owner_uid", "owner_gid"}
        if (
            set(marker) != expected
            or marker.get("schema_version") != "1"
            or marker.get("artifact_id") != "opendesign"
            or not isinstance(marker.get("store_generation"), str)
            or isinstance(marker.get("owner_uid"), bool)
            or not isinstance(marker.get("owner_uid"), int)
            or isinstance(marker.get("owner_gid"), bool)
            or not isinstance(marker.get("owner_gid"), int)
        ):
            raise ArtifactStoreError("artifact_permissions_invalid", "store_open", "OpenDesign namespace identity is invalid")
        owner_uid = int(marker["owner_uid"])
        owner_gid = int(marker["owner_gid"])
        visible_owner_uid = _mapped_namespace_id(owner_uid, Path("/proc/self/uid_map"))
        visible_owner_gid = _mapped_namespace_id(owner_gid, Path("/proc/self/gid_map"))
        for path in (self.root, self.root / NAMESPACE_MARKER):
            metadata = path.stat()
            if metadata.st_uid != visible_owner_uid or metadata.st_gid != visible_owner_gid:
                raise ArtifactStoreError(
                    "artifact_permissions_invalid",
                    "store_open",
                    "OpenDesign namespace ownership is invalid",
                )
        return marker

    def _ensure_layout(self, *, create: bool) -> None:
        for relative in ("runtime", "web", "quarantine/runtime", "quarantine/web", ".staging", ".locks"):
            path = self.root / relative
            if create:
                path.mkdir(parents=True, exist_ok=True, mode=0o750)
                path.chmod(0o750)
            elif not path.is_dir() or path.is_symlink():
                raise ArtifactStoreError("artifact_missing", "store_open", "OpenDesign artifact store layout is incomplete")

    @contextmanager
    def _digest_lock(self, kind: str, digest: str) -> Iterator[None]:
        lock_path = self.root / ".locks" / f"{kind}-{digest}.lock"
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(lock_path, flags, 0o640)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _validate_receipt(payload: object, *, kind: str, digest: str, store_generation: str) -> dict[str, Any]:
    fields = {
        "schema_version", "kind", "artifact_sha256", "runtime_artifact_sha256",
        "file_manifest_sha256", "source_file_manifest_sha256", "upstream_commit",
        "opendesign_version", "file_count", "total_size_bytes", "verifier_version",
        "store_generation", "verified_at", "compatible_runtime_artifact_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ArtifactStoreError("artifact_integrity_mismatch", "artifact_fast_verify", "OpenDesign receipt schema is invalid")
    compatible = payload.get("compatible_runtime_artifact_sha256")
    if (
        payload.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or payload.get("kind") != kind
        or payload.get("artifact_sha256") != digest
        or payload.get("store_generation") != store_generation
        or payload.get("verifier_version") != VERIFIER_VERSION
        or not is_sha256(payload.get("file_manifest_sha256"))
        or not isinstance(compatible, list)
        or not compatible
        or any(not is_sha256(item) for item in compatible)
        or payload.get("runtime_artifact_sha256") not in compatible
    ):
        raise ArtifactStoreError("artifact_integrity_mismatch", "artifact_fast_verify", "OpenDesign receipt identity is invalid")
    return payload


def _validate_kind_digest(kind: str, digest: str) -> None:
    if kind not in {"runtime", "web"} or not is_sha256(digest):
        raise ArtifactStoreError("runtime_binding_invalid", "artifact_resolve", "OpenDesign artifact identity is invalid")


def _audited_invalid_package(
    root: Path,
    *,
    kind: str,
    digest: str,
    store_generation: str,
    package_identity: tuple[int, int],
    owner_uid: int,
    owner_gid: int,
) -> bool:
    """Fail the receipt fast path after a full audit rejected this exact inode."""
    marker_path = root / "audit" / f"invalid-{kind}-{digest}.json"
    if not marker_path.exists() and not marker_path.is_symlink():
        return False
    payload = _read_json(
        marker_path,
        label="OpenDesign invalid-artifact audit marker",
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    expected = {
        "schema_version",
        "kind",
        "artifact_sha256",
        "store_generation",
        "package_device",
        "package_inode",
        "observed_at_epoch_ms",
    }
    if (
        set(payload) != expected
        or payload.get("schema_version") != "1"
        or payload.get("kind") != kind
        or payload.get("artifact_sha256") != digest
        or payload.get("store_generation") != store_generation
        or isinstance(payload.get("package_device"), bool)
        or not isinstance(payload.get("package_device"), int)
        or isinstance(payload.get("package_inode"), bool)
        or not isinstance(payload.get("package_inode"), int)
        or isinstance(payload.get("observed_at_epoch_ms"), bool)
        or not isinstance(payload.get("observed_at_epoch_ms"), int)
    ):
        raise ArtifactStoreError(
            "artifact_integrity_mismatch",
            "artifact_fast_verify",
            "OpenDesign invalid-artifact audit marker is malformed",
            differences=1,
        )
    return (int(payload["package_device"]), int(payload["package_inode"])) == package_identity


def _read_json(
    path: Path,
    *,
    label: str,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> dict[str, Any]:
    _protected_file(path, label=label, owner_uid=owner_uid, owner_gid=owner_gid)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactStoreError("artifact_integrity_mismatch", "artifact_fast_verify", f"{label} is invalid") from error
    if not isinstance(payload, dict):
        raise ArtifactStoreError("artifact_integrity_mismatch", "artifact_fast_verify", f"{label} is invalid")
    return payload


def _protected_file(
    path: Path,
    *,
    label: str,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ArtifactStoreError("artifact_missing", "artifact_fast_verify", f"{label} is missing") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_mode & 0o022
        or (owner_uid is not None and metadata.st_uid != owner_uid)
        or (owner_gid is not None and metadata.st_gid != owner_gid)
    ):
        raise ArtifactStoreError("artifact_permissions_invalid", "artifact_fast_verify", f"{label} is not protected")


def _real_directory(
    path: Path,
    *,
    label: str,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> Path:
    try:
        metadata = Path(path).lstat()
    except FileNotFoundError as error:
        raise ArtifactStoreError("artifact_missing", "artifact_fast_verify", f"{label} is missing") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_mode & 0o022
        or (owner_uid is not None and metadata.st_uid != owner_uid)
        or (owner_gid is not None and metadata.st_gid != owner_gid)
    ):
        raise ArtifactStoreError("artifact_permissions_invalid", "artifact_fast_verify", f"{label} is not protected")
    return Path(path).resolve(strict=True)


def _protect_package(root: Path, *, owner_uid: int, owner_gid: int) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            continue
        metadata = path.stat()
        mode = stat.S_IMODE(metadata.st_mode) & ~0o022
        path.chmod(mode)
        if metadata.st_uid != owner_uid or metadata.st_gid != owner_gid:
            try:
                os.chown(path, owner_uid, owner_gid)
            except PermissionError as error:
                raise ArtifactStoreError("artifact_permissions_invalid", "protect", "Cannot protect OpenDesign artifact ownership") from error
    root.chmod(stat.S_IMODE(root.stat().st_mode) & ~0o022)


def _make_owner_writable(root: Path) -> None:
    for path in root.rglob("*"):
        if not path.is_symlink():
            path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)
    root.chmod(stat.S_IMODE(root.stat().st_mode) | stat.S_IWUSR)


def _mapped_namespace_id(host_id: int, mapping_path: Path) -> int:
    """Translate a host uid/gid into the id visible in the current user namespace."""
    try:
        lines = mapping_path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError):
        return host_id
    for line in lines:
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            namespace_start, host_start, length = (int(field) for field in fields)
        except ValueError:
            continue
        if length > 0 and host_start <= host_id < host_start + length:
            return namespace_start + (host_id - host_start)
    return host_id


def _regular_file_identity(path: Path) -> tuple[int, int, int, int, int]:
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise ArtifactError("OpenDesign archive must be a regular file")
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _directory_identity(path: Path) -> tuple[int, int]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ArtifactStoreError(
            "artifact_permissions_invalid",
            "repair_identity",
            "OpenDesign repair target is not a real directory",
        )
    return metadata.st_dev, metadata.st_ino


def _fsync_tree(root: Path) -> None:
    if _sync_filesystem(root):
        return
    for current_root, directories, filenames in os.walk(root, topdown=False, followlinks=False):
        current = Path(current_root)
        for name in filenames:
            path = current / name
            if not path.is_symlink():
                descriptor = os.open(path, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        for name in directories:
            if not (current / name).is_symlink():
                _fsync_directory(current / name)
        _fsync_directory(current)


def _sync_filesystem(root: Path) -> bool:
    try:
        syncfs = ctypes.CDLL(None, use_errno=True).syncfs
    except AttributeError:
        return False
    descriptor = os.open(root, os.O_RDONLY | (os.O_DIRECTORY if hasattr(os, "O_DIRECTORY") else 0))
    try:
        syncfs.argtypes = [ctypes.c_int]
        syncfs.restype = ctypes.c_int
        if syncfs(descriptor) != 0:
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number))
    finally:
        os.close(descriptor)
    return True


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | (os.O_DIRECTORY if hasattr(os, "O_DIRECTORY") else 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _path_is_read_only_mount(path: Path) -> bool:
    resolved = path.resolve(strict=True)
    best: tuple[int, bool] | None = None
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        fields = line.split()
        if len(fields) < 6:
            continue
        mount_point = Path(fields[4].replace("\\040", " ").replace("\\134", "\\"))
        try:
            resolved.relative_to(mount_point)
        except ValueError:
            continue
        read_only = "ro" in fields[5].split(",")
        candidate = (len(mount_point.parts), read_only)
        if best is None or candidate[0] > best[0]:
            best = candidate
    return bool(best and best[1])


def _inject(injector: FailureInjector | None, phase: str) -> None:
    if injector is not None:
        injector(phase)
