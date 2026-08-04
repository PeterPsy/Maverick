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
        "toolchain",
        "patch_series",
        "certification",
        "build",
        "stage",
        "artifact",
        "native_runtime_dependencies",
        "sandbox",
    }
    if set(manifest) != expected_top_level or manifest.get("schema_version") != "3":
        raise ArtifactError("OpenDesign bundle manifest schema or fields are unsupported")
    upstream = mapping(manifest, "upstream")
    commit = required_hex(upstream, "commit", length=40)
    if commit != "276b4d8e970bc143d7ad060181a89a834e3d9caf":
        raise ArtifactError("OpenDesign upstream commit is not the reviewed pin")
    release_version = required_string(upstream, "release_version")
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
    safe_relative_path(required_string(manifest, "patch_series"))
    certification = mapping(manifest, "certification")
    safe_relative_path(required_string(certification, "record"))
    required_hex(certification, "record_sha256", length=64)
    if certification.get("separate_from_packaging") is not True:
        raise ArtifactError("OpenDesign upstream certification must remain separate")
    if manifest.get("native_runtime_dependencies") != ["better-sqlite3", "node-pty", "blake3-wasm"]:
        raise ArtifactError("OpenDesign native runtime dependency proof set is incomplete")
    selected_asset(manifest, require_artifact_digest=require_artifact_digest)


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
