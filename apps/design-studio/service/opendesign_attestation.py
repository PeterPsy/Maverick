"""OpenDesign SBOM, license, provenance, and signature operations."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
from typing import Any, Callable, Iterable

from opendesign_archive import artifact_paths
from opendesign_artifact import (
    ARTIFACT_DIGEST_FIELDS,
    ArtifactError,
    platform_key,
    read_bundle_manifest,
    reject_duplicate_pairs,
    selected_asset,
    sha256_file,
    validate_bundle_manifest,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]


def package_inventory(staging: Path) -> list[dict[str, str]]:
    packages: dict[tuple[str, str], dict[str, str]] = {}
    for path in artifact_paths(staging):
        if path.name != "package.json" or path.is_symlink() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_pairs)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        name = payload.get("name")
        version = payload.get("version")
        if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
            continue
        declared = payload.get("license")
        license_name = declared.strip() if isinstance(declared, str) and declared.strip() else "NOASSERTION"
        packages[(name, version)] = {"name": name, "version": version, "license": license_name}
    return [packages[key] for key in sorted(packages)]


def cyclonedx_sbom(packages: Iterable[dict[str, str]], *, version: str) -> dict[str, Any]:
    components = []
    for package in sorted(packages, key=lambda item: (item["name"], item["version"])):
        purl = f"pkg:npm/{_purl_name(package['name'])}@{package['version']}"
        component: dict[str, Any] = {
            "type": "library",
            "name": package["name"],
            "version": package["version"],
            "bom-ref": purl,
            "purl": purl,
        }
        if package["license"] != "NOASSERTION":
            component["licenses"] = [{"license": {"id": package["license"]}}]
        components.append(component)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "OpenDesign for Maverick",
                "version": version,
            }
        },
        "components": components,
    }


def license_inventory(
    packages: Iterable[dict[str, str]],
    *,
    upstream: dict[str, Any],
) -> dict[str, Any]:
    ordered = sorted(packages, key=lambda item: (item["name"], item["version"]))
    counts: dict[str, int] = {}
    for package in ordered:
        counts[package["license"]] = counts.get(package["license"], 0) + 1
    return {
        "schema_version": "1",
        "source": {key: upstream[key] for key in ("repository", "tag", "commit")},
        "declared_license_counts": {key: counts[key] for key in sorted(counts)},
        "packages": ordered,
        "root_license": "Apache-2.0",
    }


def notice_text(licenses: dict[str, Any]) -> str:
    packages = licenses.get("packages")
    if not isinstance(packages, list):
        raise ArtifactError("OpenDesign license inventory has no package list")
    lines = [
        "OpenDesign for Maverick — third-party notices",
        "",
        "The OpenDesign source distribution is licensed under Apache-2.0; see LICENSE.",
        "Transitive runtime package declarations captured for this artifact:",
        "",
    ]
    lines.extend(
        f"- {package['name']}@{package['version']}: {package['license']}"
        for package in packages
    )
    return "\n".join(lines) + "\n"


def provenance_payload(
    *,
    artifact_name: str,
    artifact_sha256: str,
    lockfile_sha256: str,
    patch_evidence: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    invocation = hashlib.sha256(
        f"{artifact_sha256}:{manifest['upstream']['commit']}".encode("utf-8")
    ).hexdigest()
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": artifact_name, "digest": {"sha256": artifact_sha256}}],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://maverick.local/build-types/opendesign-runtime/v1",
                "externalParameters": {
                    "source": manifest["upstream"],
                    "toolchain": manifest["toolchain"],
                    "platform": platform_key(),
                },
                "internalParameters": {
                    "patches": patch_evidence,
                    "commands": manifest["fallback_build"]["build"],
                },
                "resolvedDependencies": [
                    {
                        "uri": manifest["upstream"]["repository"],
                        "digest": {"gitCommit": manifest["upstream"]["commit"]},
                    },
                    {"uri": "pnpm-lock.yaml", "digest": {"sha256": lockfile_sha256}},
                ],
            },
            "runDetails": {
                "builder": {"id": "maverick/design-studio/package_opendesign.py"},
                "metadata": {
                    "invocationId": invocation,
                    "reproducible": True,
                    "sourceSignature": manifest["upstream"]["tag_metadata"],
                },
            },
        },
    }


def oci_provenance_payload(
    *,
    artifact_name: str,
    artifact_sha256: str,
    patch_evidence: dict[str, Any],
    startup_patch_evidence: dict[str, Any],
    rootfs_inventory_sha256: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    distribution = manifest["distribution"]
    invocation = hashlib.sha256(
        (
            f"{artifact_sha256}:{distribution['index']['digest']}:"
            f"{patch_evidence['post_sha256']}:{startup_patch_evidence['post_sha256']}:"
        ).encode("utf-8")
    ).hexdigest()
    dependencies = [
        {
            "uri": f"oci://{distribution['registry']}/{distribution['repository']}@{distribution['index']['digest']}",
            "digest": {"sha256": distribution["index"]["digest"][7:]},
        },
        {
            "uri": f"oci-manifest://{distribution['registry']}/{distribution['repository']}@{distribution['manifest']['digest']}",
            "digest": {"sha256": distribution["manifest"]["digest"][7:]},
        },
        {
            "uri": "oci-config://opendesign/linux-amd64",
            "digest": {"sha256": distribution["config"]["digest"][7:]},
        },
    ]
    dependencies.extend(
        {
            "uri": f"oci-layer://opendesign/{index:02d}",
            "digest": {"sha256": descriptor["digest"][7:]},
        }
        for index, descriptor in enumerate(distribution["layers"], start=1)
    )
    dependencies.extend(
        [
            {
                "uri": "in-toto://opendesign/upstream-slsa",
                "digest": {"sha256": distribution["attestation"]["statement"]["digest"][7:]},
            },
            {
                "uri": f"git+{manifest['upstream']['repository']}@{manifest['upstream']['commit']}#LICENSE",
                "digest": {"sha256": manifest["upstream_license"]["sha256"]},
            },
            {
                "uri": f"git+{manifest['upstream']['repository']}@{manifest['upstream']['commit']}",
                "digest": {"gitCommit": manifest["upstream"]["commit"]},
            },
        ]
    )
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": artifact_name, "digest": {"sha256": artifact_sha256}}],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://maverick.local/build-types/opendesign-oci-derivation/v1",
                "externalParameters": {
                    "distribution": distribution,
                    "platform": platform_key(),
                },
                "internalParameters": {
                    "boundaryPatch": patch_evidence,
                    "startupPatch": startup_patch_evidence,
                    "rootfsInventorySha256": rootfs_inventory_sha256,
                    "runtimeClosure": manifest["runtime_closure"],
                },
                "resolvedDependencies": dependencies,
            },
            "runDetails": {
                "builder": {"id": "maverick/design-studio/import_opendesign_oci.py"},
                "metadata": {
                    "invocationId": invocation,
                    "reproducible": True,
                    "upstreamAttestationVerified": True,
                    "upstreamAttestationTrustIdentityVerified": False,
                },
            },
        },
    }


def sign_provenance(
    provenance: Path,
    private_key: Path,
    signature: Path,
    public_key: Path,
    *,
    run: Runner = subprocess.run,
) -> None:
    if private_key.is_symlink() or not private_key.is_file():
        raise ArtifactError("OpenDesign provenance signing key must be a real file")
    _run_checked(run, ["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)])
    _run_checked(
        run,
        [
            "openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(private_key),
            "-in", str(provenance), "-out", str(signature),
        ],
    )
    verify_signature(provenance, signature, public_key, run=run)


def verify_signature(
    provenance: Path,
    signature: Path,
    public_key: Path,
    *,
    run: Runner = subprocess.run,
) -> None:
    del run
    for label, path in (
        ("signed document", provenance),
        ("signature", signature),
        ("public key", public_key),
    ):
        if path.is_symlink() or not path.is_file():
            raise ArtifactError(f"OpenDesign {label} must be a real file")
    try:
        key_bytes = _ed25519_spki_public_key(public_key.read_bytes())
        if not _verify_ed25519_raw(key_bytes, signature.read_bytes(), provenance.read_bytes()):
            raise ValueError("invalid Ed25519 signature")
    except (OSError, ValueError) as exc:
        raise ArtifactError("OpenDesign provenance signature verification failed") from exc


_ED25519_Q = 2**255 - 19
_ED25519_L = 2**252 + 27742317777372353535851937790883648493
_ED25519_D = (-121665 * pow(121666, _ED25519_Q - 2, _ED25519_Q)) % _ED25519_Q
_ED25519_I = pow(2, (_ED25519_Q - 1) // 4, _ED25519_Q)
_ED25519_IDENTITY = (0, 1)
_ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def _ed25519_spki_public_key(pem: bytes) -> bytes:
    try:
        lines = pem.decode("ascii").strip().splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("public key is not ASCII PEM") from exc
    if lines[:1] != ["-----BEGIN PUBLIC KEY-----"] or lines[-1:] != ["-----END PUBLIC KEY-----"]:
        raise ValueError("public key PEM boundary is invalid")
    try:
        der = base64.b64decode("".join(lines[1:-1]), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("public key PEM payload is invalid") from exc
    if len(der) != len(_ED25519_SPKI_PREFIX) + 32 or not der.startswith(_ED25519_SPKI_PREFIX):
        raise ValueError("public key is not a canonical Ed25519 SPKI key")
    return der[len(_ED25519_SPKI_PREFIX) :]


def _verify_ed25519_raw(public_key: bytes, signature: bytes, message: bytes) -> bool:
    if len(public_key) != 32 or len(signature) != 64:
        return False
    try:
        public_point = _ed25519_decode_point(public_key)
        r_point = _ed25519_decode_point(signature[:32])
    except ValueError:
        return False
    scalar = int.from_bytes(signature[32:], "little")
    if scalar >= _ED25519_L or public_point == _ED25519_IDENTITY:
        return False
    if _ed25519_scalar_mult(public_point, _ED25519_L) != _ED25519_IDENTITY:
        return False
    if _ed25519_scalar_mult(r_point, _ED25519_L) != _ED25519_IDENTITY:
        return False
    challenge = int.from_bytes(
        hashlib.sha512(signature[:32] + public_key + message).digest(),
        "little",
    ) % _ED25519_L
    left = _ed25519_scalar_mult(_ed25519_base_point(), scalar)
    right = _ed25519_add(r_point, _ed25519_scalar_mult(public_point, challenge))
    return left == right


def _ed25519_base_point() -> tuple[int, int]:
    y = (4 * pow(5, _ED25519_Q - 2, _ED25519_Q)) % _ED25519_Q
    return _ed25519_recover_x(y, 0), y


def _ed25519_recover_x(y: int, sign: int) -> int:
    numerator = (y * y - 1) % _ED25519_Q
    denominator = (_ED25519_D * y * y + 1) % _ED25519_Q
    x_squared = numerator * pow(denominator, _ED25519_Q - 2, _ED25519_Q) % _ED25519_Q
    x = pow(x_squared, (_ED25519_Q + 3) // 8, _ED25519_Q)
    if (x * x - x_squared) % _ED25519_Q:
        x = x * _ED25519_I % _ED25519_Q
    if (x * x - x_squared) % _ED25519_Q:
        raise ValueError("point is not on Ed25519")
    if (x & 1) != sign:
        x = _ED25519_Q - x
    return x


def _ed25519_decode_point(encoded: bytes) -> tuple[int, int]:
    if len(encoded) != 32:
        raise ValueError("Ed25519 point length is invalid")
    value = int.from_bytes(encoded, "little")
    sign = value >> 255
    y = value & ((1 << 255) - 1)
    if y >= _ED25519_Q:
        raise ValueError("Ed25519 point is not canonical")
    point = (_ed25519_recover_x(y, sign), y)
    if _ed25519_encode_point(point) != encoded:
        raise ValueError("Ed25519 point encoding is not canonical")
    return point


def _ed25519_encode_point(point: tuple[int, int]) -> bytes:
    x, y = point
    return int(y | ((x & 1) << 255)).to_bytes(32, "little")


def _ed25519_add(first: tuple[int, int], second: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = first
    x2, y2 = second
    product = _ED25519_D * x1 * x2 * y1 * y2 % _ED25519_Q
    x = (x1 * y2 + x2 * y1) * pow(1 + product, _ED25519_Q - 2, _ED25519_Q)
    y = (y1 * y2 + x1 * x2) * pow(1 - product, _ED25519_Q - 2, _ED25519_Q)
    return x % _ED25519_Q, y % _ED25519_Q


def _ed25519_scalar_mult(point: tuple[int, int], scalar: int) -> tuple[int, int]:
    result = _ED25519_IDENTITY
    addend = point
    while scalar:
        if scalar & 1:
            result = _ed25519_add(result, addend)
        addend = _ed25519_add(addend, addend)
        scalar >>= 1
    return result


def verify_artifact_set(
    manifest: dict[str, Any],
    artifact_directory: Path,
    *,
    verifier_profile: str = "current-v2",
) -> dict[str, Any]:
    validate_bundle_manifest(
        manifest,
        require_artifact_digest=True,
        verifier_profile=verifier_profile,
    )
    if artifact_directory.is_symlink() or not artifact_directory.is_dir():
        raise ArtifactError("OpenDesign artifact directory must be a real directory")
    asset = selected_asset(manifest, require_artifact_digest=True)
    paths: dict[str, Path] = {}
    for path_field, digest_field in ARTIFACT_DIGEST_FIELDS.items():
        path = _asset_path(artifact_directory, asset[path_field])
        if path.is_symlink() or not path.is_file():
            raise ArtifactError(f"OpenDesign artifact asset is missing: {asset[path_field]}")
        if sha256_file(path) != asset[digest_field]:
            raise ArtifactError(f"OpenDesign artifact asset digest mismatch: {asset[path_field]}")
        paths[path_field] = path
    if paths["file"].stat().st_size != asset["size_bytes"]:
        raise ArtifactError("OpenDesign artifact size mismatch")
    _validate_metadata_assets(paths, manifest=manifest)
    verify_signature(paths["provenance"], paths["signature"], paths["public_key"])
    return asset


def _validate_metadata_assets(paths: dict[str, Path], *, manifest: dict[str, Any]) -> None:
    file_manifest = read_bundle_manifest(paths["file_manifest"])
    if (
        file_manifest.get("schema_version") != "1"
        or not isinstance(file_manifest.get("self_excluded"), list)
        or not isinstance(file_manifest.get("files"), list)
    ):
        raise ArtifactError("OpenDesign file manifest is invalid")
    sbom = read_bundle_manifest(paths["sbom"])
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.6":
        raise ArtifactError("OpenDesign SBOM is not CycloneDX 1.6")
    licenses = read_bundle_manifest(paths["license_inventory"])
    if licenses.get("schema_version") != "1" or licenses.get("root_license") != "Apache-2.0":
        raise ArtifactError("OpenDesign license inventory is invalid")
    if not paths["notice"].read_text(encoding="utf-8").strip():
        raise ArtifactError("OpenDesign NOTICE is empty")
    provenance = read_bundle_manifest(paths["provenance"])
    archive_name = paths["file"].name
    expected = [{"name": archive_name, "digest": {"sha256": sha256_file(paths["file"])}}]
    if provenance.get("subject") != expected:
        raise ArtifactError("OpenDesign provenance subject does not match the artifact")
    try:
        build_definition = provenance["predicate"]["buildDefinition"]
        external = build_definition["externalParameters"]
        internal = build_definition["internalParameters"]
    except (KeyError, TypeError) as error:
        raise ArtifactError("OpenDesign provenance build definition is invalid") from error
    if external != {"distribution": manifest["distribution"], "platform": platform_key()}:
        raise ArtifactError("OpenDesign provenance distribution parameters differ from the pinned manifest")
    if (
        not isinstance(internal, dict)
        or set(internal) != {
            "boundaryPatch",
            "startupPatch",
            "rootfsInventorySha256",
            "runtimeClosure",
        }
        or internal.get("boundaryPatch") != manifest["boundary_patch"]
        or internal.get("startupPatch") != manifest["startup_patch"]
        or internal.get("runtimeClosure") != manifest["runtime_closure"]
        or not isinstance(internal.get("rootfsInventorySha256"), str)
        or len(internal["rootfsInventorySha256"]) != 64
    ):
        raise ArtifactError("OpenDesign provenance internal parameters differ from the pinned manifest")


def _asset_path(root: Path, relative: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ArtifactError(f"OpenDesign artifact asset escapes its directory: {relative}") from exc
    return path


def _run_checked(run: Runner, command: list[str], *, label: str = "provenance signing") -> None:
    completed = run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ArtifactError(f"OpenDesign {label} failed")


def _purl_name(name: str) -> str:
    if name.startswith("@") and "/" in name:
        scope, package = name[1:].split("/", 1)
        return f"%40{scope}/{package}"
    return name
