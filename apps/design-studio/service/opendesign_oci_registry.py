"""Digest-pinned, streaming OCI pull client for the OpenDesign release image."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import ssl
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from official_oci_validation import (
    reject_duplicate_pairs,
    validate_oci_distribution,
)


USER_AGENT = "Maverick-OpenDesign-OCI-Importer/1"
CHUNK_SIZE = 1024 * 1024


class OciRegistryError(RuntimeError):
    """Fail-closed OCI registry or release-verification error."""


@dataclass(frozen=True)
class PulledRelease:
    index: dict[str, Any]
    manifest: dict[str, Any]
    config: dict[str, Any]
    attestation_manifest: dict[str, Any]
    attestation_statement: dict[str, Any]
    layer_paths: tuple[Path, ...]


class _PinnedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_hosts: set[str]) -> None:
        super().__init__()
        self._allowed_hosts = allowed_hosts

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):  # type: ignore[no-untyped-def]
        parsed = urlparse(new_url)
        if parsed.scheme != "https" or parsed.hostname not in self._allowed_hosts:
            raise OciRegistryError("OpenDesign OCI registry attempted an unauthorized redirect")
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


class RegistryClient:
    def __init__(self, manifest: dict[str, Any], *, timeout_seconds: int = 60) -> None:
        self.distribution = validate_oci_distribution(manifest)
        self.timeout_seconds = timeout_seconds
        self.registry = self.distribution["registry"]
        self.repository = self.distribution["repository"]
        self._base = f"https://{self.registry}/v2/{self.repository}/"
        allowed_redirect_hosts = self.distribution["allowed_redirect_hosts"]
        self._opener = build_opener(
            _PinnedRedirectHandler(set(allowed_redirect_hosts)),
            _https_handler(),
        )
        self._token: str | None = None

    def pull(self, destination: Path) -> PulledRelease:
        destination = _new_real_directory(destination)
        self._check_memory_floor()
        index = self._fetch_json_descriptor(
            f"manifests/{self.distribution['reference']}",
            self.distribution["index"],
            accept=self.distribution["index"]["media_type"],
            require_registry_digest=True,
        )
        platform_manifest = _single_platform_manifest(index, self.distribution["platform"])
        _assert_oci_descriptor(platform_manifest, self.distribution["manifest"], label="platform manifest")

        image_manifest = self._fetch_json_descriptor(
            f"manifests/{self.distribution['manifest']['digest']}",
            self.distribution["manifest"],
            accept=self.distribution["manifest"]["media_type"],
        )
        _assert_oci_descriptor(image_manifest.get("config"), self.distribution["config"], label="config")
        _assert_descriptor_list(image_manifest.get("layers"), self.distribution["layers"], label="layers")
        config = self._fetch_json_descriptor(
            f"blobs/{self.distribution['config']['digest']}",
            self.distribution["config"],
            accept="application/octet-stream",
            allow_octet_stream=True,
        )
        _verify_config(config, self.distribution)

        attestation = self.distribution["attestation"]
        attestation_manifest = self._fetch_json_descriptor(
            f"manifests/{attestation['manifest']['digest']}",
            attestation["manifest"],
            accept=attestation["manifest"]["media_type"],
        )
        _assert_oci_descriptor(
            attestation_manifest.get("config"),
            attestation["config"],
            label="attestation config",
        )
        _assert_descriptor_list(
            attestation_manifest.get("layers"),
            [
                {
                    "media_type": attestation["statement"]["media_type"],
                    "digest": attestation["statement"]["digest"],
                    "size_bytes": attestation["statement"]["size_bytes"],
                }
            ],
            label="attestation layers",
        )
        self._fetch_json_descriptor(
            f"blobs/{attestation['config']['digest']}",
            attestation["config"],
            accept="application/octet-stream",
            allow_octet_stream=True,
        )
        statement = self._fetch_json_descriptor(
            f"blobs/{attestation['statement']['digest']}",
            {
                "media_type": attestation["statement"]["media_type"],
                "digest": attestation["statement"]["digest"],
                "size_bytes": attestation["statement"]["size_bytes"],
            },
            accept="application/octet-stream",
            allow_octet_stream=True,
        )
        _verify_attestation(statement, self.distribution)

        layers_root = destination / "layers"
        layers_root.mkdir(mode=0o700)
        layer_paths: list[Path] = []
        for sequence, descriptor in enumerate(self.distribution["layers"], start=1):
            path = layers_root / f"{sequence:02d}-{descriptor['digest'][7:]}.tar.gz"
            self._download_descriptor(
                f"blobs/{descriptor['digest']}",
                descriptor,
                path,
                accept="application/octet-stream",
                allow_octet_stream=True,
            )
            layer_paths.append(path)
        return PulledRelease(
            index=index,
            manifest=image_manifest,
            config=config,
            attestation_manifest=attestation_manifest,
            attestation_statement=statement,
            layer_paths=tuple(layer_paths),
        )

    def _fetch_json_descriptor(
        self,
        relative_url: str,
        descriptor: dict[str, Any],
        *,
        accept: str,
        allow_octet_stream: bool = False,
        require_registry_digest: bool = False,
    ) -> dict[str, Any]:
        response = self._request(relative_url, accept=accept)
        try:
            content_type = response.headers.get_content_type()
            allowed = {descriptor["media_type"]}
            if allow_octet_stream:
                allowed.add("application/octet-stream")
            if content_type not in allowed:
                raise OciRegistryError("OpenDesign OCI registry returned an unexpected media type")
            registry_digest = response.headers.get("Docker-Content-Digest")
            if require_registry_digest and registry_digest != descriptor["digest"]:
                raise OciRegistryError("OpenDesign OCI tag no longer resolves to the pinned digest")
            payload = _read_bounded(response, descriptor["size_bytes"])
        finally:
            response.close()
        _verify_bytes(payload, descriptor)
        try:
            value = json.loads(payload, object_pairs_hook=reject_duplicate_pairs)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise OciRegistryError("OpenDesign OCI metadata is not strict JSON") from exc
        if not isinstance(value, dict):
            raise OciRegistryError("OpenDesign OCI metadata must be a JSON object")
        return value

    def _download_descriptor(
        self,
        relative_url: str,
        descriptor: dict[str, Any],
        destination: Path,
        *,
        accept: str,
        allow_octet_stream: bool,
    ) -> None:
        if destination.exists() or destination.is_symlink():
            raise OciRegistryError("OpenDesign OCI blob destination already exists")
        response = self._request(relative_url, accept=accept)
        temporary = destination.with_suffix(destination.suffix + ".partial")
        digest = hashlib.sha256()
        size = 0
        try:
            content_type = response.headers.get_content_type()
            allowed = {descriptor["media_type"]}
            if allow_octet_stream:
                allowed.add("application/octet-stream")
            if content_type not in allowed:
                raise OciRegistryError("OpenDesign OCI registry returned an unexpected blob media type")
            with temporary.open("xb") as handle:
                while chunk := response.read(CHUNK_SIZE):
                    size += len(chunk)
                    if size > descriptor["size_bytes"]:
                        raise OciRegistryError("OpenDesign OCI blob exceeds its pinned size")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if size != descriptor["size_bytes"] or f"sha256:{digest.hexdigest()}" != descriptor["digest"]:
                raise OciRegistryError("OpenDesign OCI blob bytes do not match the pinned descriptor")
            os.replace(temporary, destination)
        except OSError as exc:
            raise OciRegistryError("OpenDesign OCI blob could not be stored safely") from exc
        finally:
            response.close()
            temporary.unlink(missing_ok=True)

    def _request(self, relative_url: str, *, accept: str) -> BinaryIO:
        try:
            token = self._registry_token()
            request = Request(
                urljoin(self._base, relative_url),
                headers={
                    "Accept": accept,
                    "Authorization": f"Bearer {token}",
                    "User-Agent": USER_AGENT,
                },
            )
            return self._opener.open(request, timeout=self.timeout_seconds)
        except OciRegistryError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise OciRegistryError("OpenDesign OCI registry request failed") from exc

    def _registry_token(self) -> str:
        if self._token is not None:
            return self._token
        query = urlencode(
            {
                "service": self.registry,
                "scope": f"repository:{self.repository}:pull",
            }
        )
        request = Request(
            f"https://{self.registry}/token?{query}",
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            response = self._opener.open(request, timeout=self.timeout_seconds)
            try:
                payload = _read_limited(response, 64 * 1024)
            finally:
                response.close()
            decoded = json.loads(payload, object_pairs_hook=reject_duplicate_pairs)
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise OciRegistryError("OpenDesign OCI registry token flow failed") from exc
        token = decoded.get("token") if isinstance(decoded, dict) else None
        if not isinstance(token, str) or not token or len(token) > 16384:
            raise OciRegistryError("OpenDesign OCI registry returned an invalid pull token")
        self._token = token
        return token

    def _check_memory_floor(self) -> None:
        available = _mem_available_bytes()
        if available < self.distribution["minimum_mem_available_bytes"]:
            raise OciRegistryError("OpenDesign OCI import memory safety floor is not satisfied")


def _https_handler():
    from urllib.request import HTTPSHandler

    return HTTPSHandler(context=ssl.create_default_context())


def _new_real_directory(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise OciRegistryError("OpenDesign OCI import destination must not exist")
    path.mkdir(parents=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise OciRegistryError("OpenDesign OCI import destination must be a real directory")
    return path.resolve(strict=True)


def _read_bounded(response: BinaryIO, expected_size: int) -> bytes:
    limit = expected_size + 1
    payload = response.read(limit)
    if len(payload) != expected_size:
        raise OciRegistryError("OpenDesign OCI metadata size does not match the pin")
    if response.read(1):
        raise OciRegistryError("OpenDesign OCI metadata exceeds its pinned size")
    return payload


def _read_limited(response: BinaryIO, limit: int) -> bytes:
    payload = response.read(limit + 1)
    if len(payload) > limit:
        raise OciRegistryError("OpenDesign OCI response exceeds its safety limit")
    return payload


def _verify_bytes(payload: bytes, descriptor: dict[str, Any]) -> None:
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    if len(payload) != descriptor["size_bytes"] or digest != descriptor["digest"]:
        raise OciRegistryError("OpenDesign OCI metadata bytes do not match the pinned descriptor")


def _single_platform_manifest(index: dict[str, Any], platform: dict[str, str]) -> dict[str, Any]:
    manifests = index.get("manifests")
    if index.get("mediaType") != "application/vnd.oci.image.index.v1+json" or not isinstance(manifests, list):
        raise OciRegistryError("OpenDesign OCI index schema is invalid")
    matches = [item for item in manifests if isinstance(item, dict) and item.get("platform") == platform]
    if len(matches) != 1:
        raise OciRegistryError("OpenDesign OCI index does not contain exactly one pinned platform")
    return matches[0]


def _assert_oci_descriptor(actual: object, expected: dict[str, Any], *, label: str) -> None:
    if not isinstance(actual, dict):
        raise OciRegistryError(f"OpenDesign OCI {label} descriptor is missing")
    normalized = {
        "media_type": actual.get("mediaType"),
        "digest": actual.get("digest"),
        "size_bytes": actual.get("size"),
    }
    if normalized != expected:
        raise OciRegistryError(f"OpenDesign OCI {label} descriptor changed")


def _assert_descriptor_list(actual: object, expected: list[dict[str, Any]], *, label: str) -> None:
    if not isinstance(actual, list) or len(actual) != len(expected):
        raise OciRegistryError(f"OpenDesign OCI {label} descriptor count changed")
    for actual_item, expected_item in zip(actual, expected, strict=True):
        _assert_oci_descriptor(actual_item, expected_item, label=label)


def _verify_config(config: dict[str, Any], distribution: dict[str, Any]) -> None:
    labels = config.get("config", {}).get("Labels") if isinstance(config.get("config"), dict) else None
    if not isinstance(labels, dict):
        raise OciRegistryError("OpenDesign OCI config labels are missing")
    if labels.get("org.opencontainers.image.revision") != distribution["expected_revision"]:
        raise OciRegistryError("OpenDesign OCI revision label changed")
    if labels.get("org.opencontainers.image.version") != distribution["expected_version"]:
        raise OciRegistryError("OpenDesign OCI version label changed")
    image_config = config.get("config")
    if image_config.get("Entrypoint") != ["/sbin/tini", "--"]:
        raise OciRegistryError("OpenDesign OCI entrypoint changed")
    if image_config.get("Cmd") != ["node", "apps/daemon/dist/cli.js", "--no-open"]:
        raise OciRegistryError("OpenDesign OCI command changed")


def _verify_attestation(statement: dict[str, Any], distribution: dict[str, Any]) -> None:
    attestation = distribution["attestation"]
    if statement.get("_type") != "https://in-toto.io/Statement/v1":
        raise OciRegistryError("OpenDesign OCI attestation statement type changed")
    if statement.get("predicateType") != attestation["statement"]["predicate_type"]:
        raise OciRegistryError("OpenDesign OCI attestation predicate type changed")
    subjects = statement.get("subject")
    expected = attestation["subject_manifest_digest"][7:]
    if not isinstance(subjects, list) or not any(
        isinstance(subject, dict)
        and isinstance(subject.get("digest"), dict)
        and subject["digest"].get("sha256") == expected
        for subject in subjects
    ):
        raise OciRegistryError("OpenDesign OCI attestation subject changed")
    predicate = statement.get("predicate")
    build_definition = predicate.get("buildDefinition") if isinstance(predicate, dict) else None
    external = build_definition.get("externalParameters") if isinstance(build_definition, dict) else None
    request = external.get("request") if isinstance(external, dict) else None
    args = request.get("args") if isinstance(request, dict) else None
    if not isinstance(args, dict) or args.get("label:org.opencontainers.image.revision") != distribution["expected_revision"]:
        raise OciRegistryError("OpenDesign OCI attestation revision changed")


def _mem_available_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError) as exc:
        raise OciRegistryError("OpenDesign OCI import cannot read MemAvailable") from exc
    raise OciRegistryError("OpenDesign OCI import cannot read MemAvailable")


__all__ = ["OciRegistryError", "PulledRelease", "RegistryClient"]
