"""Fail-closed verification for immutable OpenDesign static web overlays."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

from opendesign_attestation import verify_signature
from opendesign_store_manifest import StoreManifestError, verify_store_manifest
from opendesign_supply_chain import read_json, sha256_file


OVERLAY_SCHEMA_VERSION = "2"
SUPPORTED_OVERLAY_SCHEMA_VERSIONS = frozenset({"1", OVERLAY_SCHEMA_VERSION})
TRUST_SCHEMA_VERSION = "1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_FIELDS = {
    "schema_version",
    "web_overlay_sha256",
    "static_archive",
    "file_manifest",
    "compatibility",
    "inputs",
    "sbom",
    "licenses",
    "notice",
    "provenance",
    "signature",
}
_COMPATIBILITY_FIELDS = {
    "runtime_artifact_sha256",
    "od_version",
    "upstream_commit",
    "platform",
}


class WebOverlayError(RuntimeError):
    """Raised when an overlay is unsafe, untrusted, or incompatible."""


@dataclass(frozen=True)
class VerifiedWebOverlay:
    web_overlay_sha256: str
    path: Path
    static_dir: Path
    od_version: str
    upstream_commit: str
    compatible_runtime_artifact_sha256: frozenset[str]
    file_manifest_sha256: str
    toolchain_sha256: str


def web_overlay_identity(
    *,
    static_archive_sha256: str,
    file_manifest_sha256: str,
    sbom_sha256: str,
    licenses_sha256: str,
    notice_sha256: str,
    compatibility: dict[str, Any],
    inputs: dict[str, Any],
) -> str:
    """Bind v2 overlay identity to content, modes, provenance inputs, and compatibility."""
    payload = {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "static_archive_sha256": static_archive_sha256,
        "file_manifest_sha256": file_manifest_sha256,
        "sbom_sha256": sbom_sha256,
        "licenses_sha256": licenses_sha256,
        "notice_sha256": notice_sha256,
        "compatibility": compatibility,
        "inputs": inputs,
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def discover_verified_overlays(
    registry_root: Path,
    *,
    trust_contract: Path,
    required_digests: set[str] | frozenset[str] | None = None,
) -> dict[str, VerifiedWebOverlay]:
    registry = _real_directory(registry_root, label="web overlay registry")
    required = set(required_digests or set())
    if any(not SHA256_RE.fullmatch(value) for value in required):
        raise WebOverlayError("required web overlay digest is invalid")
    candidates = required or {
        path.name
        for path in registry.iterdir()
        if path.is_dir() and not path.is_symlink() and SHA256_RE.fullmatch(path.name)
    }
    verified: dict[str, VerifiedWebOverlay] = {}
    for digest in sorted(candidates):
        path = registry / digest
        if not path.exists():
            if digest in required:
                raise WebOverlayError("required web overlay is not materialized")
            continue
        verified[digest] = verify_web_overlay(
            path,
            expected_digest=digest,
            registry_root=registry,
            trust_contract=trust_contract,
        )
    return verified


def verify_web_overlay(
    overlay_root: Path,
    *,
    expected_digest: str,
    registry_root: Path,
    trust_contract: Path,
) -> VerifiedWebOverlay:
    return _verify_web_overlay(
        overlay_root,
        expected_digest=expected_digest,
        registry_root=registry_root,
        trust_contract=trust_contract,
        require_digest_name=True,
    )


def verify_staged_web_overlay(
    overlay_root: Path,
    *,
    expected_digest: str,
    registry_root: Path,
    trust_contract: Path,
) -> VerifiedWebOverlay:
    """Verify a same-registry temporary directory before atomic publication."""
    return _verify_web_overlay(
        overlay_root,
        expected_digest=expected_digest,
        registry_root=registry_root,
        trust_contract=trust_contract,
        require_digest_name=False,
    )


def _verify_web_overlay(
    overlay_root: Path,
    *,
    expected_digest: str,
    registry_root: Path,
    trust_contract: Path,
    require_digest_name: bool,
) -> VerifiedWebOverlay:
    if not SHA256_RE.fullmatch(expected_digest):
        raise WebOverlayError("web overlay digest must be lowercase SHA-256")
    registry = _real_directory(registry_root, label="web overlay registry")
    overlay = _real_directory(overlay_root, label="web overlay")
    try:
        overlay.relative_to(registry)
    except ValueError as exc:
        raise WebOverlayError("web overlay escapes the verified registry") from exc
    if overlay.parent != registry or (require_digest_name and overlay.name != expected_digest):
        raise WebOverlayError("web overlay is not in its digest-named registry directory")

    trust_key = _load_trust_root(trust_contract)
    manifest_path = _real_file(overlay, "manifest.json")
    signature_path = _real_file(overlay, "manifest.sig")
    try:
        verify_signature(manifest_path, signature_path, trust_key)
    except Exception as exc:
        raise WebOverlayError("web overlay signature is not trusted") from exc

    manifest = read_json(manifest_path)
    schema_version = manifest.get("schema_version")
    if set(manifest) != _MANIFEST_FIELDS or schema_version not in SUPPORTED_OVERLAY_SCHEMA_VERSIONS:
        raise WebOverlayError("web overlay manifest schema is invalid")
    if manifest.get("web_overlay_sha256") != expected_digest:
        raise WebOverlayError("web overlay digest does not match its registry directory")

    archive = _descriptor(manifest.get("static_archive"), "static archive")
    if archive["path"] != "static.tar.gz":
        raise WebOverlayError("web overlay archive descriptor is invalid")
    if schema_version == "1" and archive["sha256"] != expected_digest:
        raise WebOverlayError("web overlay v1 archive identity is invalid")
    _verify_descriptor(overlay, archive, label="static archive")
    file_manifest = _descriptor(manifest.get("file_manifest"), "file manifest")
    if file_manifest["path"] != "files.json":
        raise WebOverlayError("web overlay file manifest path is invalid")
    files_path = _verify_descriptor(overlay, file_manifest, label="file manifest")

    descriptors = {}
    for field, expected_path in (
        ("sbom", "sbom.cdx.json"),
        ("licenses", "licenses.json"),
        ("notice", "NOTICE"),
        ("provenance", "provenance.json"),
    ):
        descriptor = _descriptor(manifest.get(field), field)
        if descriptor["path"] != expected_path:
            raise WebOverlayError(f"web overlay {field} path is invalid")
        descriptors[field] = _verify_descriptor(overlay, descriptor, label=field)
    signature = manifest.get("signature")
    if signature != {"algorithm": "Ed25519", "path": "manifest.sig"}:
        raise WebOverlayError("web overlay signature descriptor is invalid")

    compatibility = manifest.get("compatibility")
    if not isinstance(compatibility, dict) or set(compatibility) != _COMPATIBILITY_FIELDS:
        raise WebOverlayError("web overlay compatibility schema is invalid")
    runtime_digests = compatibility.get("runtime_artifact_sha256")
    if (
        not isinstance(runtime_digests, list)
        or not runtime_digests
        or runtime_digests != sorted(set(runtime_digests))
        or any(not isinstance(value, str) or not SHA256_RE.fullmatch(value) for value in runtime_digests)
    ):
        raise WebOverlayError("web overlay runtime compatibility is invalid")
    version = _trimmed_text(compatibility.get("od_version"), "OpenDesign version")
    upstream_commit = _trimmed_text(compatibility.get("upstream_commit"), "upstream commit")
    if not re.fullmatch(r"[0-9a-f]{40}", upstream_commit):
        raise WebOverlayError("web overlay upstream commit is invalid")
    platform = compatibility.get("platform")
    if not isinstance(platform, dict) or set(platform) != {"os", "architecture"}:
        raise WebOverlayError("web overlay platform compatibility is invalid")
    _trimmed_text(platform.get("os"), "platform os")
    _trimmed_text(platform.get("architecture"), "platform architecture")

    inputs = manifest.get("inputs")
    required_input_fields = {
        "lockfile_sha256",
        "package_graph_sha256",
        "web_build_patch_sha256",
        "web_react_patch_sha256",
        "node",
        "pnpm",
        "toolchain_sha256",
    }
    if not isinstance(inputs, dict) or set(inputs) != required_input_fields:
        raise WebOverlayError("web overlay build inputs are incomplete")
    for field in required_input_fields - {"node", "pnpm"}:
        if not isinstance(inputs.get(field), str) or not SHA256_RE.fullmatch(str(inputs[field])):
            raise WebOverlayError(f"web overlay {field} is invalid")
    _trimmed_text(inputs.get("node"), "Node version")
    _trimmed_text(inputs.get("pnpm"), "pnpm version")

    if schema_version == OVERLAY_SCHEMA_VERSION:
        identity = web_overlay_identity(
            static_archive_sha256=archive["sha256"],
            file_manifest_sha256=file_manifest["sha256"],
            sbom_sha256=_descriptor(manifest["sbom"], "sbom")["sha256"],
            licenses_sha256=_descriptor(manifest["licenses"], "licenses")["sha256"],
            notice_sha256=_descriptor(manifest["notice"], "notice")["sha256"],
            compatibility=compatibility,
            inputs=inputs,
        )
        if identity != expected_digest:
            raise WebOverlayError("web overlay v2 identity does not match its protected inputs")

    static_dir = _real_directory(overlay / "static", label="web overlay static directory")
    if schema_version == "1":
        _verify_file_manifest(static_dir, files_path)
    else:
        try:
            verify_store_manifest(static_dir, read_json(files_path))
        except StoreManifestError as exc:
            raise WebOverlayError("web overlay manifest-v2 content or modes are invalid") from exc
    _verify_evidence_documents(descriptors, expected_digest=expected_digest)
    _reject_unknown_top_level(overlay)
    return VerifiedWebOverlay(
        web_overlay_sha256=expected_digest,
        path=overlay,
        static_dir=static_dir,
        od_version=version,
        upstream_commit=upstream_commit,
        compatible_runtime_artifact_sha256=frozenset(runtime_digests),
        file_manifest_sha256=file_manifest["sha256"],
        toolchain_sha256=str(inputs["toolchain_sha256"]),
    )


def _load_trust_root(contract_path: Path) -> Path:
    contract_path = Path(contract_path)
    if contract_path.is_symlink() or not contract_path.is_file():
        raise WebOverlayError("web overlay trust contract must be a real file")
    contract = read_json(contract_path)
    if set(contract) != {"schema_version", "algorithm", "public_key", "public_key_sha256"}:
        raise WebOverlayError("web overlay trust contract schema is invalid")
    if contract.get("schema_version") != TRUST_SCHEMA_VERSION or contract.get("algorithm") != "Ed25519":
        raise WebOverlayError("web overlay trust algorithm is unsupported")
    relative = _safe_relative(contract.get("public_key"), "trust public key")
    public_key = (contract_path.parent / relative).resolve(strict=True)
    if public_key.is_symlink() or not public_key.is_file():
        raise WebOverlayError("web overlay trust public key must be a real file")
    if sha256_file(public_key) != contract.get("public_key_sha256"):
        raise WebOverlayError("web overlay trust public key digest mismatch")
    return public_key


def _verify_file_manifest(static_dir: Path, manifest_path: Path) -> None:
    manifest = read_json(manifest_path)
    if set(manifest) != {"schema_version", "files"} or manifest.get("schema_version") != "1":
        raise WebOverlayError("web overlay file manifest schema is invalid")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise WebOverlayError("web overlay file manifest is empty")
    expected_paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size_bytes"}:
            raise WebOverlayError("web overlay file entry is invalid")
        relative = _safe_relative(entry.get("path"), "overlay file")
        if relative in expected_paths:
            raise WebOverlayError("web overlay file manifest contains duplicates")
        expected_paths.add(relative)
        path = _real_file(static_dir, relative)
        if path.stat().st_size != entry.get("size_bytes") or sha256_file(path) != entry.get("sha256"):
            raise WebOverlayError(f"web overlay file digest mismatch: {relative}")
    actual_paths = {
        path.relative_to(static_dir).as_posix()
        for path in static_dir.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if actual_paths != expected_paths:
        raise WebOverlayError("web overlay static directory differs from its file manifest")


def _verify_evidence_documents(paths: dict[str, Path], *, expected_digest: str) -> None:
    for field in ("sbom", "licenses", "provenance"):
        read_json(paths[field])
    provenance = read_json(paths["provenance"])
    subject = provenance.get("subject")
    if subject != {"web_overlay_sha256": expected_digest}:
        raise WebOverlayError("web overlay provenance subject is invalid")


def _descriptor(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256", "size_bytes"}:
        raise WebOverlayError(f"web overlay {label} descriptor is invalid")
    relative = _safe_relative(value.get("path"), label)
    digest = value.get("sha256")
    size = value.get("size_bytes")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise WebOverlayError(f"web overlay {label} digest is invalid")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise WebOverlayError(f"web overlay {label} size is invalid")
    return {"path": relative, "sha256": digest, "size_bytes": size}


def _verify_descriptor(root: Path, descriptor: dict[str, Any], *, label: str) -> Path:
    path = _real_file(root, descriptor["path"])
    if path.stat().st_size != descriptor["size_bytes"] or sha256_file(path) != descriptor["sha256"]:
        raise WebOverlayError(f"web overlay {label} digest mismatch")
    return path


def _real_directory(path: Path, *, label: str) -> Path:
    path = Path(path)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise WebOverlayError(f"{label} is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise WebOverlayError(f"{label} must be a real directory")
    return path.resolve(strict=True)


def _real_file(root: Path, relative: str) -> Path:
    safe = _safe_relative(relative, "overlay path")
    candidate = root.joinpath(*PurePosixPath(safe).parts)
    try:
        mode = candidate.lstat().st_mode
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise WebOverlayError("web overlay file escapes its registry directory") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise WebOverlayError("web overlay files must be real regular files")
    return resolved


def _safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise WebOverlayError(f"{label} path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise WebOverlayError(f"{label} path is unsafe")
    return path.as_posix()


def _trimmed_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise WebOverlayError(f"{label} is invalid")
    return value


def _reject_unknown_top_level(root: Path) -> None:
    expected = {
        "manifest.json",
        "manifest.sig",
        "static.tar.gz",
        "files.json",
        "sbom.cdx.json",
        "licenses.json",
        "NOTICE",
        "provenance.json",
        "static",
    }
    if {path.name for path in root.iterdir()} != expected:
        raise WebOverlayError("web overlay contains undeclared top-level material")
