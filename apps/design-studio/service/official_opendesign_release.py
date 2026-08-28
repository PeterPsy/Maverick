"""Install and run an official OpenDesign OCI release without modifying it.

The OCI manifest digest is the package identity.  Layer application is an
installation operation: every regular-file byte and symlink target comes from
the verified upstream layers.  Maverick metadata is written next to ``rootfs``
and never into the official filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
from typing import Any, Callable
from uuid import uuid4

from official_oci_validation import (
    OFFICIAL_REGISTRY,
    OFFICIAL_REPOSITORY,
    OfficialOciValidationError,
    reject_duplicate_pairs,
    validate_oci_distribution,
)
from opendesign_oci_layout import OciLayoutError, apply_layers
from opendesign_oci_registry import OciRegistryError, PulledRelease, RegistryClient


OFFICIAL_RELEASE_FILE = Path(__file__).with_name("opendesign_official_release.json")
OFFICIAL_MANIFEST_DIGEST = "sha256:170f56cdeb3a213423af150d4095b7729814eaf0ad26a99be7fab2344f0f5cd1"
INSTALL_RECEIPT = "official-release.json"
ROOTFS_SNAPSHOT = "rootfs.snapshot.json"
ROOTFS_SNAPSHOT_SCHEMA = "1"
RELEASE_DESCRIPTOR = "release-descriptor.json"
OFFICIAL_SOURCE_REPOSITORY = "https://github.com/nexu-io/open-design.git"
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
REQUIRED_ROOTFS_PATHS = (
    "app/apps/daemon/dist/cli.js",
    "app/apps/web/out/index.html",
    "usr/local/bin/node",
    "lib/ld-musl-x86_64.so.1",
    "sbin/tini",
)


class OfficialReleaseError(RuntimeError):
    """Fail-closed official package validation or installation error."""


@dataclass(frozen=True)
class OfficialRelease:
    """Strict release identity and the upstream OCI lock."""

    version: str
    source_repository: str
    source_tag: str
    source_commit: str
    registry: str
    repository: str
    reference: str
    platform: dict[str, str]
    index_digest: str
    manifest_digest: str
    config_digest: str
    entrypoint: tuple[str, ...]
    command: tuple[str, ...]
    working_directory: str
    data_directory: str
    customizations: tuple[str, ...]
    oci_lock: dict[str, Any]

    @property
    def image(self) -> str:
        return f"{self.registry}/{self.repository}"

    @property
    def digest_key(self) -> str:
        return self.manifest_digest.removeprefix("sha256:")

    def registry_manifest(self) -> dict[str, Any]:
        """Return the legacy client shape, containing official metadata only."""
        return {
            "upstream": {
                "commit": self.source_commit,
                "release_version": self.version,
            },
            "distribution": self.oci_lock,
        }

    def descriptor(self) -> dict[str, Any]:
        """Return the canonical user-selected official release lock."""
        return {
            "schema_version": "1",
            "kind": "official_opendesign_oci_release",
            "version": self.version,
            "source": {
                "repository": self.source_repository,
                "tag": self.source_tag,
                "commit": self.source_commit,
            },
            "oci": self.oci_lock,
            "runtime": {
                "entrypoint": list(self.entrypoint),
                "command": list(self.command),
                "working_directory": self.working_directory,
                "data_directory": self.data_directory,
            },
            "customizations": [],
        }


@dataclass(frozen=True)
class OfficialInstallation:
    """One verified official root filesystem and its external receipt."""

    path: Path
    rootfs: Path
    release: OfficialRelease
    rootfs_snapshot_sha256: str
    installed_at: str


def load_official_release(
    path: Path = OFFICIAL_RELEASE_FILE,
    *,
    require_bundled_pin: bool | None = None,
) -> OfficialRelease:
    """Load a strict zero-customization official release descriptor."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise OfficialReleaseError("official OpenDesign release descriptor is unreadable") from error
    return load_official_release_payload(
        payload,
        require_bundled_pin=(
            path.resolve(strict=False) == OFFICIAL_RELEASE_FILE.resolve(strict=False)
            if require_bundled_pin is None
            else require_bundled_pin
        ),
    )


def load_official_release_payload(
    payload: object,
    *,
    require_bundled_pin: bool = False,
) -> OfficialRelease:
    """Validate one bundled or user-selected official release lock."""
    expected = {"schema_version", "kind", "version", "source", "oci", "runtime", "customizations"}
    if (
        not isinstance(payload, dict)
        or set(payload) != expected
        or payload.get("schema_version") != "1"
        or payload.get("kind") != "official_opendesign_oci_release"
    ):
        raise OfficialReleaseError("official OpenDesign release descriptor schema is unsupported")
    customizations = payload.get("customizations")
    if customizations != []:
        raise OfficialReleaseError("official OpenDesign release customizations must be empty")
    source = _mapping(payload, "source")
    if set(source) != {"repository", "tag", "commit"}:
        raise OfficialReleaseError("official OpenDesign source identity is invalid")
    runtime = _mapping(payload, "runtime")
    if set(runtime) != {"entrypoint", "command", "working_directory", "data_directory"}:
        raise OfficialReleaseError("official OpenDesign runtime identity is invalid")
    oci = _mapping(payload, "oci")
    try:
        validate_oci_distribution(
            {
                "upstream": {
                    "commit": _string(source, "commit"),
                    "release_version": _string(payload, "version"),
                },
                "distribution": oci,
            }
        )
    except OfficialOciValidationError as error:
        raise OfficialReleaseError(str(error)) from error
    release = OfficialRelease(
        version=_string(payload, "version"),
        source_repository=_string(source, "repository"),
        source_tag=_string(source, "tag"),
        source_commit=_hex(source, "commit", 40),
        registry=_string(oci, "registry"),
        repository=_string(oci, "repository"),
        reference=_string(oci, "reference"),
        platform=dict(_mapping(oci, "platform")),
        index_digest=_descriptor_digest(oci, "index"),
        manifest_digest=_descriptor_digest(oci, "manifest"),
        config_digest=_descriptor_digest(oci, "config"),
        entrypoint=_string_tuple(runtime, "entrypoint"),
        command=_string_tuple(runtime, "command"),
        working_directory=_absolute_path(runtime, "working_directory"),
        data_directory=_absolute_path(runtime, "data_directory"),
        customizations=(),
        oci_lock=oci,
    )
    if release.source_repository != OFFICIAL_SOURCE_REPOSITORY:
        raise OfficialReleaseError("OpenDesign source repository is not official")
    if not VERSION_PATTERN.fullmatch(release.version):
        raise OfficialReleaseError("official OpenDesign version is invalid")
    if release.source_tag != f"open-design-v{release.version}":
        raise OfficialReleaseError("official OpenDesign source tag does not match the version")
    if release.registry != OFFICIAL_REGISTRY or release.repository != OFFICIAL_REPOSITORY:
        raise OfficialReleaseError("OpenDesign OCI origin is not official")
    if require_bundled_pin and release.manifest_digest != OFFICIAL_MANIFEST_DIGEST:
        raise OfficialReleaseError("official OpenDesign 0.16.1 manifest digest changed")
    if release.entrypoint != ("/sbin/tini", "--"):
        raise OfficialReleaseError("official OpenDesign OCI entrypoint changed")
    if release.command != ("node", "apps/daemon/dist/cli.js", "--no-open"):
        raise OfficialReleaseError("official OpenDesign OCI command changed")
    if release.working_directory != "/app" or release.data_directory != "/app/.od":
        raise OfficialReleaseError("official OpenDesign OCI filesystem contract changed")
    return release


def install_official_release(
    destination: Path,
    *,
    release: OfficialRelease | None = None,
    registry_client_factory: Callable[[dict[str, Any]], RegistryClient] = RegistryClient,
) -> OfficialInstallation:
    """Pull, verify, and atomically install one official OCI root filesystem."""
    selected = release or load_official_release()
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        return verify_official_installation(destination, expected_release=selected)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.install-{uuid4().hex}"
    downloads = staging / "download"
    rootfs = staging / "rootfs"
    try:
        staging.mkdir(mode=0o750)
        client = registry_client_factory(selected.registry_manifest())
        pulled = client.pull(downloads)
        _verify_pulled_identity(pulled, selected)
        apply_layers(pulled.layer_paths, rootfs)
        _verify_required_rootfs(rootfs)
        snapshot = snapshot_rootfs(rootfs)
        snapshot_sha = _canonical_sha256(snapshot)
        _write_json(staging / ROOTFS_SNAPSHOT, snapshot, mode=0o640)
        _write_json(staging / RELEASE_DESCRIPTOR, selected.descriptor(), mode=0o640)
        receipt = {
            "schema_version": "1",
            "kind": "official_opendesign_installation",
            "image": selected.image,
            "reference": selected.reference,
            "version": selected.version,
            "source_commit": selected.source_commit,
            "index_digest": selected.index_digest,
            "manifest_digest": selected.manifest_digest,
            "config_digest": selected.config_digest,
            "rootfs_snapshot_sha256": snapshot_sha,
            "customizations": [],
            "installed_at": datetime.now(tz=UTC).isoformat(),
        }
        _write_json(staging / INSTALL_RECEIPT, receipt, mode=0o640)
        shutil.rmtree(downloads)
        os.replace(staging, destination)
    except (OfficialReleaseError, OciRegistryError, OciLayoutError):
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise OfficialReleaseError("official OpenDesign installation failed safely") from error
    return verify_official_installation(destination, expected_release=selected)


def verify_official_installation(
    path: Path,
    *,
    expected_release: OfficialRelease | None = None,
    verify_contents: bool = True,
) -> OfficialInstallation:
    """Verify external receipt identity and, optionally, every rootfs entry."""
    root = _real_directory(path, "official installation")
    release = expected_release or _installed_release(root)
    rootfs = _real_directory(root / "rootfs", "official rootfs")
    try:
        receipt = json.loads(
            (root / INSTALL_RECEIPT).read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
        )
        snapshot = json.loads(
            (root / ROOTFS_SNAPSHOT).read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise OfficialReleaseError("official OpenDesign installation metadata is unreadable") from error
    expected_receipt = {
        "schema_version",
        "kind",
        "image",
        "reference",
        "version",
        "source_commit",
        "index_digest",
        "manifest_digest",
        "config_digest",
        "rootfs_snapshot_sha256",
        "customizations",
        "installed_at",
    }
    if not isinstance(receipt, dict) or set(receipt) != expected_receipt:
        raise OfficialReleaseError("official OpenDesign installation receipt is invalid")
    identities = {
        "image": release.image,
        "reference": release.reference,
        "version": release.version,
        "source_commit": release.source_commit,
        "index_digest": release.index_digest,
        "manifest_digest": release.manifest_digest,
        "config_digest": release.config_digest,
        "customizations": [],
    }
    if any(receipt.get(key) != value for key, value in identities.items()):
        raise OfficialReleaseError("official OpenDesign installation identity differs from the selected release")
    snapshot_sha = _canonical_sha256(snapshot)
    if receipt.get("rootfs_snapshot_sha256") != snapshot_sha:
        raise OfficialReleaseError("official OpenDesign rootfs snapshot metadata is inconsistent")
    _verify_required_rootfs(rootfs)
    if verify_contents:
        verify_rootfs_snapshot(rootfs, snapshot)
    return OfficialInstallation(
        path=root,
        rootfs=rootfs,
        release=release,
        rootfs_snapshot_sha256=snapshot_sha,
        installed_at=_string(receipt, "installed_at"),
    )


def snapshot_rootfs(rootfs: Path) -> dict[str, Any]:
    """Build deterministic external evidence for every installed rootfs entry."""
    root = _real_directory(rootfs, "official rootfs")
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISREG(metadata.st_mode):
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "mode": mode,
                    "size_bytes": metadata.st_size,
                    "sha256": _file_sha256(path),
                }
            )
        elif stat.S_ISDIR(metadata.st_mode):
            entries.append({"path": relative, "type": "directory", "mode": mode})
        elif stat.S_ISLNK(metadata.st_mode):
            entries.append({"path": relative, "type": "symlink", "target": os.readlink(path)})
        else:
            raise OfficialReleaseError(f"official rootfs contains unsupported entry: {relative}")
    return {
        "schema_version": ROOTFS_SNAPSHOT_SCHEMA,
        "algorithm": "sha256",
        "entry_count": len(entries),
        "entries": entries,
    }


def verify_rootfs_snapshot(rootfs: Path, expected: object) -> None:
    """Fail if the installed official rootfs differs in any entry."""
    if not isinstance(expected, dict) or set(expected) != {"schema_version", "algorithm", "entry_count", "entries"}:
        raise OfficialReleaseError("official rootfs snapshot schema is invalid")
    if expected.get("schema_version") != ROOTFS_SNAPSHOT_SCHEMA or expected.get("algorithm") != "sha256":
        raise OfficialReleaseError("official rootfs snapshot algorithm is unsupported")
    actual = snapshot_rootfs(rootfs)
    if actual != expected:
        raise OfficialReleaseError("official OpenDesign rootfs differs from its verified installation snapshot")


def build_official_launch_command(
    release: OfficialRelease,
    *,
    rootfs: Path,
    data_dir: Path,
    port: int,
    api_token: str,
    bridge_mode: str = "disabled",
) -> tuple[list[str], dict[str, str]]:
    """Plan a disposable full-rootfs launch of the official OCI command."""
    root = _real_directory(rootfs, "official rootfs")
    data = _real_directory(data_dir, "disposable OpenDesign data directory")
    _verify_required_rootfs(root)
    if bridge_mode not in {"disabled", "enabled"}:
        raise OfficialReleaseError("OpenDesign bridge mode is invalid")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise OfficialReleaseError("OpenDesign port is invalid")
    if not isinstance(api_token, str) or not api_token or "\x00" in api_token:
        raise OfficialReleaseError("OpenDesign API token is invalid")
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise OfficialReleaseError("bubblewrap is required for the disposable official release proof")
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NODE_ENV": "production",
        "NODE_OPTIONS": "--max-old-space-size=192",
        "OD_API_TOKEN": api_token,
        "OD_BIND_HOST": "127.0.0.1",
        "OD_DATA_DIR": release.data_directory,
        "OD_PORT": str(port),
        "MAVERICK_OPENDESIGN_MODEL_BRIDGE": bridge_mode,
        "MAVERICK_OPENDESIGN_DELEGATION_BRIDGE": bridge_mode,
    }
    command = [
        bwrap,
        "--die-with-parent",
        "--unshare-user",
        "--uid",
        "1001",
        "--gid",
        "1001",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--ro-bind",
        str(root),
        "/",
        "--bind",
        str(data),
        release.data_directory,
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
    ]
    for key, value in environment.items():
        command.extend(["--setenv", key, value])
    command.extend(["--chdir", release.working_directory, *release.entrypoint, *release.command])
    return command, environment


def launch_disposable_official_release(
    installation: OfficialInstallation,
    *,
    data_dir: Path,
    port: int,
    api_token: str,
    bridge_mode: str = "disabled",
    stdout: Any = subprocess.DEVNULL,
    stderr: Any = subprocess.DEVNULL,
) -> subprocess.Popen[bytes]:
    """Start the verified official command for a bounded disposable proof."""
    command, environment = build_official_launch_command(
        installation.release,
        rootfs=installation.rootfs,
        data_dir=data_dir,
        port=port,
        api_token=api_token,
        bridge_mode=bridge_mode,
    )
    host_env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), **environment}
    try:
        return subprocess.Popen(command, env=host_env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
    except OSError as error:
        raise OfficialReleaseError("official OpenDesign disposable process could not start") from error


def _verify_pulled_identity(pulled: PulledRelease, release: OfficialRelease) -> None:
    manifest_digest = "sha256:" + hashlib.sha256(
        json.dumps(pulled.manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    # RegistryClient already verifies the descriptor bytes.  Re-encoding is
    # not an OCI digest proof, so use it only as a structural sanity value and
    # retain the descriptor identity as the authoritative package identity.
    if not pulled.layer_paths or not isinstance(pulled.config, dict) or not manifest_digest.startswith("sha256:"):
        raise OfficialReleaseError("official OpenDesign OCI pull is incomplete")
    labels = pulled.config.get("config", {}).get("Labels") if isinstance(pulled.config.get("config"), dict) else None
    if not isinstance(labels, dict):
        raise OfficialReleaseError("official OpenDesign OCI labels are missing")
    if labels.get("org.opencontainers.image.revision") != release.source_commit:
        raise OfficialReleaseError("official OpenDesign OCI revision differs from the selected release")
    if labels.get("org.opencontainers.image.version") != release.version:
        raise OfficialReleaseError("official OpenDesign OCI version differs from the selected release")


def _installed_release(root: Path) -> OfficialRelease:
    descriptor = root / RELEASE_DESCRIPTOR
    if descriptor.exists() or descriptor.is_symlink():
        return load_official_release(descriptor, require_bundled_pin=False)
    if root.name == OFFICIAL_MANIFEST_DIGEST.removeprefix("sha256:"):
        return load_official_release()
    raise OfficialReleaseError("official OpenDesign installation release descriptor is missing")


def _verify_required_rootfs(rootfs: Path) -> None:
    for relative in REQUIRED_ROOTFS_PATHS:
        path = rootfs / relative
        try:
            metadata = path.lstat()
        except FileNotFoundError as error:
            raise OfficialReleaseError(f"official OpenDesign rootfs is missing {relative}") from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OfficialReleaseError(f"official OpenDesign rootfs path is not a regular file: {relative}")
    index = rootfs / "app/apps/web/out/index.html"
    try:
        html = index.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as error:
        raise OfficialReleaseError("official OpenDesign native web entrypoint is unreadable") from error
    if "__next" not in html.lower() and "open design" not in html.lower() and "opendesign" not in html.lower():
        raise OfficialReleaseError("official OpenDesign native web entrypoint identity is missing")


def _real_directory(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise OfficialReleaseError(f"{label} is unavailable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise OfficialReleaseError(f"{label} must be a real directory")
    return resolved


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise OfficialReleaseError(f"official OpenDesign field {key} must be an object")
    return value


def _string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or "\x00" in value:
        raise OfficialReleaseError(f"official OpenDesign field {key} must be a non-empty string")
    return value


def _hex(payload: dict[str, Any], key: str, length: int) -> str:
    value = _string(payload, key)
    if len(value) != length or any(character not in "0123456789abcdef" for character in value):
        raise OfficialReleaseError(f"official OpenDesign field {key} must be lowercase hexadecimal")
    return value


def _descriptor_digest(payload: dict[str, Any], key: str) -> str:
    descriptor = _mapping(payload, key)
    digest = _string(descriptor, "digest")
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise OfficialReleaseError(f"official OpenDesign {key} digest is invalid")
    return digest


def _string_tuple(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise OfficialReleaseError(f"official OpenDesign field {key} must be a non-empty string list")
    return tuple(value)


def _absolute_path(payload: dict[str, Any], key: str) -> str:
    value = _string(payload, key)
    if not value.startswith("/") or ".." in Path(value).parts:
        raise OfficialReleaseError(f"official OpenDesign field {key} must be an absolute contained path")
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload: object) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _write_json(path: Path, payload: object, *, mode: int) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        os.write(descriptor, body)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "OFFICIAL_MANIFEST_DIGEST",
    "OfficialInstallation",
    "OfficialRelease",
    "OfficialReleaseError",
    "build_official_launch_command",
    "install_official_release",
    "launch_disposable_official_release",
    "load_official_release",
    "load_official_release_payload",
    "snapshot_rootfs",
    "verify_official_installation",
    "verify_rootfs_snapshot",
]
