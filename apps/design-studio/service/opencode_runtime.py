"""Install and verify the pinned technical OpenCode CLI used by API profiles."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile
from typing import BinaryIO, Callable
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


CHUNK_SIZE = 1024 * 1024
RECEIPT = "installation.json"
RUNTIME_RELATIVE_PATH = Path("opencode/1.14.17")
SANDBOX_BINARY_PATH = Path("/artifacts/opendesign") / RUNTIME_RELATIVE_PATH / "bin/opencode"


class OpenCodeRuntimeError(RuntimeError):
    """The pinned model-access CLI runtime failed closed."""


@dataclass(frozen=True)
class OpenCodeRuntimeSpec:
    version: str
    package: str
    url: str
    archive_size: int
    archive_sha256: str
    binary_size: int
    binary_sha256: str


BUNDLED_OPENCODE = OpenCodeRuntimeSpec(
    version="1.14.17",
    package="opencode-linux-x64",
    url="https://registry.npmjs.org/opencode-linux-x64/-/opencode-linux-x64-1.14.17.tgz",
    archive_size=50_981_093,
    archive_sha256="53d8d8384c7dd0636909c11235a44748c6892d520eff6fe989cb5bec8c778d0c",
    binary_size=142_784_893,
    binary_sha256="089bd3bafc13fe1fe17813b49fc04badaf88b5c55372da86d931b06b3aa548d9",
)


def install_opencode_runtime(
    artifact_namespace: Path,
    *,
    spec: OpenCodeRuntimeSpec = BUNDLED_OPENCODE,
    open_url: Callable[[str], BinaryIO] | None = None,
) -> Path:
    destination = artifact_namespace / RUNTIME_RELATIVE_PATH
    if destination.exists() or destination.is_symlink():
        return verify_opencode_runtime(destination, spec=spec)
    destination.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.install-{uuid4().hex}"
    archive = staging / "package.tgz"
    try:
        staging.mkdir(mode=0o750)
        _download(spec, archive, open_url=open_url)
        binary = staging / "bin/opencode"
        binary.parent.mkdir(mode=0o750)
        _extract_verified_package(archive, binary, spec)
        archive.unlink()
        receipt = _receipt(spec)
        (staging / RECEIPT).write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(staging, destination)
    except Exception as error:
        shutil.rmtree(staging, ignore_errors=True)
        if isinstance(error, OpenCodeRuntimeError):
            raise
        raise OpenCodeRuntimeError("OpenCode model runtime installation failed safely") from error
    return verify_opencode_runtime(destination, spec=spec)


def verify_opencode_runtime(
    destination: Path,
    *,
    spec: OpenCodeRuntimeSpec = BUNDLED_OPENCODE,
) -> Path:
    try:
        metadata = destination.lstat()
        receipt_path = destination / RECEIPT
        binary = destination / "bin/opencode"
        receipt_metadata = receipt_path.lstat()
        binary_metadata = binary.lstat()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OpenCodeRuntimeError("OpenCode model runtime is unreadable") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(receipt_metadata.st_mode)
        or not stat.S_ISREG(receipt_metadata.st_mode)
        or stat.S_ISLNK(binary_metadata.st_mode)
        or not stat.S_ISREG(binary_metadata.st_mode)
        or receipt != _receipt(spec)
        or binary_metadata.st_size != spec.binary_size
        or not binary_metadata.st_mode & 0o111
        or binary_metadata.st_mode & 0o022
        or _file_sha256(binary) != spec.binary_sha256
    ):
        raise OpenCodeRuntimeError("OpenCode model runtime integrity check failed")
    return binary


def _download(
    spec: OpenCodeRuntimeSpec,
    path: Path,
    *,
    open_url: Callable[[str], BinaryIO] | None,
) -> None:
    response = (open_url or _open_pinned_url)(spec.url)
    digest = sha256()
    total = 0
    try:
        with path.open("xb") as target:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > spec.archive_size:
                    raise OpenCodeRuntimeError("OpenCode package exceeded its pinned size")
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
    finally:
        response.close()
    if total != spec.archive_size or digest.hexdigest() != spec.archive_sha256:
        raise OpenCodeRuntimeError("OpenCode package digest does not match its pin")


def _extract_verified_package(
    archive: Path,
    destination: Path,
    spec: OpenCodeRuntimeSpec,
) -> None:
    try:
        with tarfile.open(archive, "r:gz") as package:
            archive_members = package.getmembers()
            members = {member.name: member for member in archive_members}
            if (
                len(archive_members) != 2
                or set(members) != {"package/package.json", "package/bin/opencode"}
            ):
                raise OpenCodeRuntimeError("OpenCode package layout is invalid")
            if any(not member.isfile() for member in members.values()):
                raise OpenCodeRuntimeError("OpenCode package contains an unsafe entry")
            manifest_stream = package.extractfile(members["package/package.json"])
            binary_stream = package.extractfile(members["package/bin/opencode"])
            if manifest_stream is None or binary_stream is None:
                raise OpenCodeRuntimeError("OpenCode package content is missing")
            manifest_bytes = manifest_stream.read(64 * 1024 + 1)
            manifest = json.loads(manifest_bytes)
            if (
                len(manifest_bytes) > 64 * 1024
                or not isinstance(manifest, dict)
                or manifest.get("name") != spec.package
                or manifest.get("version") != spec.version
            ):
                raise OpenCodeRuntimeError("OpenCode package identity is invalid")
            _write_verified_binary(binary_stream, destination, spec)
    except (OSError, tarfile.TarError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OpenCodeRuntimeError("OpenCode package is invalid") from error


def _write_verified_binary(
    source: BinaryIO,
    destination: Path,
    spec: OpenCodeRuntimeSpec,
) -> None:
    digest = sha256()
    total = 0
    with destination.open("xb") as target:
        while True:
            chunk = source.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > spec.binary_size:
                raise OpenCodeRuntimeError("OpenCode executable exceeded its pinned size")
            digest.update(chunk)
            target.write(chunk)
        target.flush()
        os.fsync(target.fileno())
    if total != spec.binary_size or digest.hexdigest() != spec.binary_sha256:
        raise OpenCodeRuntimeError("OpenCode executable digest does not match its pin")
    destination.chmod(0o555)


def _receipt(spec: OpenCodeRuntimeSpec) -> dict[str, object]:
    return {
        "schema_version": "1",
        "kind": "design-studio-opencode-model-runtime",
        "version": spec.version,
        "package": spec.package,
        "archive_size": spec.archive_size,
        "archive_sha256": spec.archive_sha256,
        "binary_size": spec.binary_size,
        "binary_sha256": spec.binary_sha256,
    }


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


class _PinnedRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):  # type: ignore[no-untyped-def]
        parsed = urlparse(new_url)
        if parsed.scheme != "https" or parsed.hostname != "registry.npmjs.org":
            raise OpenCodeRuntimeError("OpenCode registry attempted an unauthorized redirect")
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def _open_pinned_url(url: str) -> BinaryIO:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "registry.npmjs.org":
        raise OpenCodeRuntimeError("OpenCode package origin is invalid")
    opener = build_opener(_PinnedRedirectHandler())
    return opener.open(Request(url, headers={"User-Agent": "Maverick-Model-Bridge/1"}), timeout=60)


__all__ = [
    "BUNDLED_OPENCODE",
    "OpenCodeRuntimeError",
    "OpenCodeRuntimeSpec",
    "RUNTIME_RELATIVE_PATH",
    "SANDBOX_BINARY_PATH",
    "install_opencode_runtime",
    "verify_opencode_runtime",
]
