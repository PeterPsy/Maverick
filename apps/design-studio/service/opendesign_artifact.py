"""OpenDesign artifact manifest, platform selection, and digest primitives."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
from typing import Any, Iterable
from uuid import uuid4


SHA256_LENGTH = 64
ARTIFACT_DIGEST_FIELDS = {
    "file": "sha256",
    "file_manifest": "file_manifest_sha256",
    "sbom": "sbom_sha256",
    "license_inventory": "license_inventory_sha256",
    "notice": "notice_sha256",
    "provenance": "provenance_sha256",
    "signature": "signature_sha256",
    "public_key": "public_key_sha256",
}


class ArtifactError(RuntimeError):
    """Fail-closed artifact validation error."""


def read_bundle_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_pairs)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ArtifactError(f"OpenDesign bundle manifest is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise ArtifactError("OpenDesign bundle manifest must be a JSON object")
    return payload


def validate_bundle_manifest(manifest: dict[str, Any], *, require_artifact_digest: bool) -> None:
    expected_top_level = {
        "schema_version",
        "upstream",
        "upstream_license",
        "distribution",
        "toolchain",
        "certification",
        "fallback_build",
        "runtime_closure",
        "boundary_patch",
        "ui_patch",
        "artifact",
        "native_runtime_dependencies",
        "sandbox",
    }
    if set(manifest) != expected_top_level or manifest.get("schema_version") != "4":
        raise ArtifactError("OpenDesign bundle manifest schema or fields are unsupported")
    upstream = mapping(manifest, "upstream")
    commit = required_hex(upstream, "commit", length=40)
    if commit != "276b4d8e970bc143d7ad060181a89a834e3d9caf":
        raise ArtifactError("OpenDesign upstream commit is not the reviewed pin")
    release_version = required_string(upstream, "release_version")
    upstream_license = mapping(manifest, "upstream_license")
    if set(upstream_license) != {"path", "sha256"}:
        raise ArtifactError("OpenDesign upstream license fields are unsupported")
    safe_relative_path(required_string(upstream_license, "path"))
    if required_string(upstream_license, "sha256") != "9d95806a26532623360eb84bb17d298f394b55ef73fb4c0796d99b4319b2b0da":
        raise ArtifactError("OpenDesign upstream license digest changed")
    release_identity = mapping(upstream, "release_identity")
    if required_string(release_identity, "package_version") != release_version:
        raise ArtifactError("OpenDesign release identity version does not match release_version")
    toolchain = mapping(manifest, "toolchain")
    if required_string(toolchain, "node") != "~24":
        raise ArtifactError("OpenDesign Node toolchain must stay pinned to ~24")
    if required_string(toolchain, "package_manager") != "pnpm@10.33.2":
        raise ArtifactError("OpenDesign package manager must stay pinned to pnpm@10.33.2")
    if toolchain.get("via_corepack") is not True:
        raise ArtifactError("OpenDesign pnpm must be selected through Corepack")
    if toolchain.get("corepack_enable") != ["corepack", "enable", "--install-directory"]:
        raise ArtifactError("OpenDesign Corepack shim command is not pinned")
    validate_oci_distribution(manifest)
    fallback = mapping(manifest, "fallback_build")
    if set(fallback) != {"patch_series", "build", "stage"}:
        raise ArtifactError("OpenDesign fallback build fields are unsupported")
    safe_relative_path(required_string(fallback, "patch_series"))
    mapping(fallback, "build")
    mapping(fallback, "stage")
    certification = mapping(manifest, "certification")
    safe_relative_path(required_string(certification, "record"))
    required_hex(certification, "record_sha256", length=64)
    if certification.get("separate_from_packaging") is not True:
        raise ArtifactError("OpenDesign upstream certification must remain separate")
    if manifest.get("native_runtime_dependencies") != ["better-sqlite3", "node-pty", "blake3-wasm"]:
        raise ArtifactError("OpenDesign native runtime dependency proof set is incomplete")
    closure = mapping(manifest, "runtime_closure")
    if set(closure) != {
        "app_root",
        "node",
        "musl_loader",
        "library_paths",
        "daemon_entrypoint",
        "required_native_modules",
        "blocked_optional_native_modules",
    }:
        raise ArtifactError("OpenDesign runtime closure fields are unsupported")
    for key in ("app_root", "node", "musl_loader", "daemon_entrypoint"):
        safe_relative_path(required_string(closure, key))
    libraries = closure.get("library_paths")
    if not isinstance(libraries, list) or not libraries:
        raise ArtifactError("OpenDesign runtime library paths must be a non-empty list")
    for value in libraries:
        if not isinstance(value, str):
            raise ArtifactError("OpenDesign runtime library path must be a string")
        safe_relative_path(value)
    if closure.get("required_native_modules") != ["better-sqlite3", "blake3-wasm"]:
        raise ArtifactError("OpenDesign required OCI native dependency set changed")
    if closure.get("blocked_optional_native_modules") != ["node-pty"]:
        raise ArtifactError("OpenDesign blocked OCI native dependency set changed")
    boundary = mapping(manifest, "boundary_patch")
    if set(boundary) != {"path", "pre_sha256", "post_sha256", "required_environment"}:
        raise ArtifactError("OpenDesign boundary patch fields are unsupported")
    if required_string(boundary, "path") != "app/apps/daemon/dist/server.js":
        raise ArtifactError("OpenDesign boundary patch path is not authorized")
    if required_string(boundary, "pre_sha256") != "61c966b4a3a99e7098e37a943436e8b5d52563d1bace24a0e398b200ac0135e8":
        raise ArtifactError("OpenDesign boundary patch preimage is not authorized")
    if boundary.get("required_environment") != "OD_REQUIRE_API_TOKEN_ON_LOOPBACK":
        raise ArtifactError("OpenDesign boundary patch environment is not authorized")
    post_sha256 = boundary.get("post_sha256")
    if require_artifact_digest and not is_sha256(post_sha256):
        raise ArtifactError("OpenDesign boundary patch postimage is not pinned")
    if post_sha256 is not None and not is_sha256(post_sha256):
        raise ArtifactError("OpenDesign boundary patch postimage must be null or lowercase SHA-256")
    ui_patch = mapping(manifest, "ui_patch")
    if set(ui_patch) != {"path", "pre_sha256", "post_sha256", "capabilities"}:
        raise ArtifactError("OpenDesign UI patch fields are unsupported")
    if required_string(ui_patch, "path") != "app/apps/web/out/index.html":
        raise ArtifactError("OpenDesign UI patch path is not authorized")
    if required_string(ui_patch, "pre_sha256") != "c17994dfe25730e8dc293cd1dc8221e7e918b63ff6a3756f732c0132d2b2c694":
        raise ArtifactError("OpenDesign UI patch preimage is not authorized")
    if required_string(ui_patch, "post_sha256") != "970dc7a4986cc68968b4defba8b2b6a0d28529356b69f6e471b03f2d04c45880":
        raise ArtifactError("OpenDesign UI patch postimage is not authorized")
    if ui_patch.get("capabilities") != [
        "hide_native_chat",
        "hide_home_composer",
        "hide_recent_projects",
        "maverick_theme",
        "project_navigation_bridge",
    ]:
        raise ArtifactError("OpenDesign UI patch capability set changed")
    selected_asset(manifest, require_artifact_digest=require_artifact_digest)


def validate_oci_distribution(manifest: dict[str, Any]) -> dict[str, Any]:
    distribution = mapping(manifest, "distribution")
    expected_fields = {
        "primary",
        "registry",
        "repository",
        "reference",
        "platform",
        "index",
        "manifest",
        "config",
        "layers",
        "attestation",
        "expected_revision",
        "expected_version",
        "allowed_redirect_hosts",
        "max_blob_size_bytes",
        "minimum_mem_available_bytes",
    }
    if set(distribution) != expected_fields or distribution.get("primary") != "oci_import":
        raise ArtifactError("OpenDesign OCI distribution fields are unsupported")
    if distribution.get("registry") != "ghcr.io" or distribution.get("repository") != "nexu-io/od":
        raise ArtifactError("OpenDesign OCI registry identity changed")
    if distribution.get("reference") != "0.16.1":
        raise ArtifactError("OpenDesign OCI reference changed")
    if distribution.get("platform") != {"os": "linux", "architecture": "amd64"}:
        raise ArtifactError("OpenDesign OCI platform is not authorized")
    if distribution.get("expected_revision") != manifest["upstream"]["commit"]:
        raise ArtifactError("OpenDesign OCI revision does not match upstream")
    if distribution.get("expected_version") != manifest["upstream"]["release_version"]:
        raise ArtifactError("OpenDesign OCI version does not match upstream")
    if distribution.get("allowed_redirect_hosts") != ["ghcr.io", "pkg-containers.githubusercontent.com"]:
        raise ArtifactError("OpenDesign OCI redirect policy changed")
    max_blob_size = distribution.get("max_blob_size_bytes")
    minimum_memory = distribution.get("minimum_mem_available_bytes")
    if not _positive_integer(max_blob_size) or max_blob_size > 128 * 1024 * 1024:
        raise ArtifactError("OpenDesign OCI blob limit is invalid")
    if not _positive_integer(minimum_memory) or minimum_memory < 3 * 1024 * 1024 * 1024:
        raise ArtifactError("OpenDesign OCI memory floor is invalid")
    _validate_oci_descriptor(
        mapping(distribution, "index"),
        media_type="application/vnd.oci.image.index.v1+json",
        label="index",
    )
    manifest_descriptor = _validate_oci_descriptor(
        mapping(distribution, "manifest"),
        media_type="application/vnd.oci.image.manifest.v1+json",
        label="manifest",
    )
    _validate_oci_descriptor(
        mapping(distribution, "config"),
        media_type="application/vnd.oci.image.config.v1+json",
        label="config",
    )
    layers = distribution.get("layers")
    if not isinstance(layers, list) or not layers:
        raise ArtifactError("OpenDesign OCI layers must be a non-empty list")
    layer_digests: set[str] = set()
    for layer in layers:
        if not isinstance(layer, dict):
            raise ArtifactError("OpenDesign OCI layer descriptor must be an object")
        descriptor = _validate_oci_descriptor(
            layer,
            media_type="application/vnd.oci.image.layer.v1.tar+gzip",
            label="layer",
        )
        if descriptor["size_bytes"] > max_blob_size:
            raise ArtifactError("OpenDesign OCI layer exceeds its pinned size limit")
        if descriptor["digest"] in layer_digests:
            raise ArtifactError("OpenDesign OCI layer digest is duplicated")
        layer_digests.add(descriptor["digest"])
    attestation = mapping(distribution, "attestation")
    if set(attestation) != {"manifest", "config", "statement", "subject_manifest_digest"}:
        raise ArtifactError("OpenDesign OCI attestation fields are unsupported")
    _validate_oci_descriptor(
        mapping(attestation, "manifest"),
        media_type="application/vnd.oci.image.manifest.v1+json",
        label="attestation manifest",
    )
    _validate_oci_descriptor(
        mapping(attestation, "config"),
        media_type="application/vnd.oci.image.config.v1+json",
        label="attestation config",
    )
    statement = mapping(attestation, "statement")
    if set(statement) != {"media_type", "predicate_type", "digest", "size_bytes"}:
        raise ArtifactError("OpenDesign OCI attestation statement descriptor is invalid")
    _validate_oci_descriptor(
        {key: statement[key] for key in ("media_type", "digest", "size_bytes")},
        media_type="application/vnd.in-toto+json",
        label="attestation statement",
    )
    if statement.get("predicate_type") != "https://slsa.dev/provenance/v1":
        raise ArtifactError("OpenDesign OCI attestation predicate type changed")
    if attestation.get("subject_manifest_digest") != manifest_descriptor["digest"]:
        raise ArtifactError("OpenDesign OCI attestation subject pin changed")
    return distribution


def _validate_oci_descriptor(
    descriptor: dict[str, Any],
    *,
    media_type: str,
    label: str,
) -> dict[str, Any]:
    if set(descriptor) != {"media_type", "digest", "size_bytes"}:
        raise ArtifactError(f"OpenDesign OCI {label} descriptor fields are invalid")
    if descriptor.get("media_type") != media_type:
        raise ArtifactError(f"OpenDesign OCI {label} media type changed")
    digest = descriptor.get("digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:") or not is_sha256(digest[7:]):
        raise ArtifactError(f"OpenDesign OCI {label} digest is invalid")
    if not _positive_integer(descriptor.get("size_bytes")):
        raise ArtifactError(f"OpenDesign OCI {label} size is invalid")
    return descriptor


def selected_asset(manifest: dict[str, Any], *, require_artifact_digest: bool) -> dict[str, Any]:
    artifact = mapping(manifest, "artifact")
    assets = mapping(artifact, "assets")
    selected = mapping(assets, platform_key())
    expected_fields = {"size_bytes", *ARTIFACT_DIGEST_FIELDS, *ARTIFACT_DIGEST_FIELDS.values()}
    if set(selected) != expected_fields:
        raise ArtifactError("OpenDesign platform artifact has unknown or missing fields")
    for path_field, digest_field in ARTIFACT_DIGEST_FIELDS.items():
        safe_relative_path(required_string(selected, path_field))
        digest = selected.get(digest_field)
        if require_artifact_digest and not is_sha256(digest):
            raise ArtifactError(f"OpenDesign {digest_field} for {platform_key()} is not pinned")
        if digest is not None and not is_sha256(digest):
            raise ArtifactError(f"OpenDesign {digest_field} must be null or lowercase SHA-256")
    size = selected.get("size_bytes")
    if require_artifact_digest and not _positive_integer(size):
        raise ArtifactError(f"OpenDesign artifact size for {platform_key()} is not pinned")
    if size is not None and not _positive_integer(size):
        raise ArtifactError("OpenDesign artifact size must be null or a positive integer")
    return selected


def platform_key(*, system: str | None = None, machine: str | None = None) -> str:
    normalized_system = (system or platform.system()).strip().lower()
    normalized_machine = (machine or platform.machine()).strip().lower()
    architecture = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86_64": "x86_64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(normalized_machine)
    if normalized_system not in {"linux", "darwin", "windows"} or architecture is None:
        raise ArtifactError(f"Unsupported OpenDesign artifact platform: {normalized_system}-{normalized_machine}")
    return f"{normalized_system}-{architecture}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ArtifactError(f"Cannot hash OpenDesign asset: {path.name}") from exc
    return digest.hexdigest()


def write_canonical_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def safe_relative_path(value: str) -> str:
    path = PurePosixPath(str(value or ""))
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or path.as_posix() in {".", ""}:
        raise ArtifactError(f"Unsafe OpenDesign artifact path: {value!r}")
    return path.as_posix().rstrip("/")


def reject_duplicate_pairs(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ArtifactError(f"OpenDesign bundle manifest {key} must be an object")
    return value


def required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or value.strip() != value:
        raise ArtifactError(f"OpenDesign bundle manifest {key} must be a non-empty trimmed string")
    return value


def required_hex(payload: dict[str, Any], key: str, *, length: int) -> str:
    value = required_string(payload, key)
    if len(value) != length or value.lower() != value or any(char not in "0123456789abcdef" for char in value):
        raise ArtifactError(f"OpenDesign bundle manifest {key} must be lowercase hexadecimal")
    return value


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == SHA256_LENGTH and value == value.lower() and all(
        char in "0123456789abcdef" for char in value
    )


def _positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
