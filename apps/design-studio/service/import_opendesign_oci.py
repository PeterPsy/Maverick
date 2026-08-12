#!/usr/bin/env python3
"""Import, derive, attest, and reproduce the pinned OpenDesign OCI artifact."""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from uuid import uuid4

from opendesign_archive import FILE_MANIFEST_PATH, create_file_manifest, write_deterministic_archive
from opendesign_artifact import (
    ARTIFACT_DIGEST_FIELDS,
    ArtifactError,
    platform_key,
    read_bundle_manifest,
    selected_asset,
    sha256_file,
    validate_bundle_manifest,
    write_canonical_json,
)
from opendesign_attestation import (
    cyclonedx_sbom,
    license_inventory,
    notice_text,
    oci_provenance_payload,
    package_inventory,
    sign_provenance,
    verify_artifact_set,
)
from opendesign_oci_layout import OciLayoutError, apply_layers
from opendesign_oci_patch import BoundaryPatchError, apply_boundary_patch
from opendesign_oci_registry import OciRegistryError, RegistryClient
from opendesign_oci_stage import OciStageError, runtime_node_command, stage_runtime_closure
from opendesign_process import activate_runtime_attachment, signal_guard
from opendesign_source import SourceError


SERVICE_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = SERVICE_ROOT / "opendesign_bundle.json"


class OciImportError(RuntimeError):
    """Fail-closed reproducible OCI derivation error."""


@dataclass(frozen=True)
class DerivationResult:
    output_root: Path
    artifact_sha256: str
    artifact_size_bytes: int
    file_manifest_sha256: str
    rootfs_inventory_sha256: str
    patch_evidence: dict[str, Any]


def import_reproducible_artifact(
    output_directory: Path,
    *,
    source_repository: Path,
    signing_key: Path,
    manifest: dict[str, Any],
    work_parent: Path,
    pnpm_store: Path,
    runtime_session_id: str | None,
) -> dict[str, Any]:
    validate_bundle_manifest(manifest, require_artifact_digest=False)
    signing_key = _real_file(signing_key, label="OpenDesign OCI provenance signing key")
    source_repository = _real_directory(source_repository, create=False, label="OpenDesign source repository")
    pnpm_store = _real_directory(pnpm_store, create=True, label="OpenDesign pnpm store")
    work_parent = _real_directory(work_parent, create=True, label="OpenDesign OCI work root")
    output_directory = _real_directory(output_directory, create=True, label="OpenDesign artifact output")
    asset = selected_asset(manifest, require_artifact_digest=False)
    results: list[DerivationResult] = []
    with tempfile.TemporaryDirectory(prefix="maverick-opendesign-oci-", dir=work_parent) as temporary:
        temporary_root = Path(temporary)
        for sequence in (1, 2):
            result_root = temporary_root / f"import-{sequence}"
            result_root.mkdir()
            results.append(
                derive_once(
                    result_root,
                    source_repository=source_repository,
                    signing_key=signing_key,
                    manifest=manifest,
                    asset=asset,
                    pnpm_store=pnpm_store,
                    runtime_session_id=runtime_session_id,
                )
            )
        _assert_reproducible(results, asset)
        first = results[0]
        for path_field in ARTIFACT_DIGEST_FIELDS:
            _publish_file(first.output_root / asset[path_field], output_directory / asset[path_field])
        pins = _artifact_pins(output_directory, asset)
        pinned_manifest = _with_artifact_pins(
            manifest,
            pins,
        )
        verify_artifact_set(pinned_manifest, output_directory)
    return {
        "artifact": str(output_directory / asset["file"]),
        "artifact_sha256": pins["sha256"],
        "artifact_size_bytes": pins["size_bytes"],
        "artifact_pins": pins,
        "file_manifest_sha256": pins["file_manifest_sha256"],
        "rootfs_inventory_sha256": results[0].rootfs_inventory_sha256,
        "boundary_patch": results[0].patch_evidence,
        "oci_index_digest": manifest["distribution"]["index"]["digest"],
        "oci_manifest_digest": manifest["distribution"]["manifest"]["digest"],
        "reproducible_imports": 2,
        "platform": platform_key(),
    }


def derive_once(
    result_root: Path,
    *,
    source_repository: Path,
    signing_key: Path,
    manifest: dict[str, Any],
    asset: dict[str, Any],
    pnpm_store: Path,
    runtime_session_id: str | None,
) -> DerivationResult:
    pull_root = result_root / "pull"
    release = RegistryClient(manifest).pull(pull_root)
    rootfs = result_root / "rootfs"
    apply_layers(release.layer_paths, rootfs)
    rootfs_inventory = create_file_manifest(rootfs)
    rootfs_inventory_sha256 = _canonical_payload_sha256(rootfs_inventory)
    patch_evidence = apply_boundary_patch(rootfs, manifest)
    staging = result_root / "staging"
    stage_runtime_closure(rootfs, staging, manifest=manifest, service_root=SERVICE_ROOT)
    native_probe = _probe_native_runtime(staging, manifest)

    metadata_root = staging / "maverick"
    metadata_root.mkdir()
    oci_evidence = {
        "schema_version": "1",
        "index_digest": manifest["distribution"]["index"]["digest"],
        "manifest_digest": manifest["distribution"]["manifest"]["digest"],
        "config_digest": manifest["distribution"]["config"]["digest"],
        "layer_digests": [item["digest"] for item in manifest["distribution"]["layers"]],
        "attestation_statement_digest": manifest["distribution"]["attestation"]["statement"]["digest"],
        "rootfs_inventory_sha256": rootfs_inventory_sha256,
        "native_probe": native_probe,
    }
    write_canonical_json(metadata_root / "oci.json", oci_evidence)
    write_canonical_json(metadata_root / "boundary-patch.json", patch_evidence)
    packages = package_inventory(staging)
    sbom = cyclonedx_sbom(packages, version=manifest["upstream"]["release_version"])
    licenses = license_inventory(packages, upstream=manifest["upstream"])
    notice = notice_text(licenses) + (
        "\nMaverick derived patch notice:\n"
        f"- {patch_evidence['path']} was modified to require the technical bearer on loopback.\n"
        "- Embedded apps/web/out was excluded; signed static web overlays are released independently.\n"
    )
    write_canonical_json(metadata_root / "sbom.cdx.json", sbom)
    write_canonical_json(metadata_root / "licenses.json", licenses)
    (metadata_root / "NOTICE").write_text(notice, encoding="utf-8")
    file_manifest = create_file_manifest(staging, exclude={FILE_MANIFEST_PATH})
    write_canonical_json(staging / FILE_MANIFEST_PATH, file_manifest)

    output_root = result_root / "output"
    output_root.mkdir()
    artifact_path = output_root / asset["file"]
    write_deterministic_archive(staging, artifact_path)
    shutil.copy2(staging / FILE_MANIFEST_PATH, output_root / asset["file_manifest"])
    write_canonical_json(output_root / asset["sbom"], sbom)
    write_canonical_json(output_root / asset["license_inventory"], licenses)
    (output_root / asset["notice"]).write_text(notice, encoding="utf-8")
    provenance = oci_provenance_payload(
        artifact_name=asset["file"],
        artifact_sha256=sha256_file(artifact_path),
        patch_evidence=patch_evidence,
        rootfs_inventory_sha256=rootfs_inventory_sha256,
        manifest=manifest,
    )
    provenance_path = output_root / asset["provenance"]
    write_canonical_json(provenance_path, provenance)
    sign_provenance(
        provenance_path,
        signing_key,
        output_root / asset["signature"],
        output_root / asset["public_key"],
    )
    result = DerivationResult(
        output_root=output_root,
        artifact_sha256=sha256_file(artifact_path),
        artifact_size_bytes=artifact_path.stat().st_size,
        file_manifest_sha256=sha256_file(output_root / asset["file_manifest"]),
        rootfs_inventory_sha256=rootfs_inventory_sha256,
        patch_evidence=patch_evidence,
    )
    shutil.rmtree(pull_root)
    shutil.rmtree(rootfs)
    shutil.rmtree(staging)
    return result


def _probe_native_runtime(staging: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    closure = manifest["runtime_closure"]
    script = (
        "for (const name of JSON.parse(process.argv[1])) { require(name); console.log(name + ':ok'); }"
    )
    command = [
        *runtime_node_command(staging, manifest),
        "-e",
        script,
        json.dumps(closure["required_native_modules"]),
    ]
    completed = subprocess.run(
        command,
        cwd=staging / "app/apps/daemon",
        env={
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "NO_COLOR": "1",
            "PATH": "/usr/bin:/bin",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise OciImportError("OpenDesign imported native runtime probe failed")
    expected_lines = [f"{name}:ok" for name in closure["required_native_modules"]]
    if completed.stdout.splitlines() != expected_lines:
        raise OciImportError("OpenDesign imported native runtime probe output changed")
    optional_status: dict[str, str] = {}
    for name in closure["blocked_optional_native_modules"]:
        optional = subprocess.run(
            [*runtime_node_command(staging, manifest), "-e", "require(process.argv[1])", name],
            cwd=staging / "app/apps/daemon",
            env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "NO_COLOR": "1", "PATH": "/usr/bin:/bin"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=30,
        )
        optional_status[name] = "unavailable_upstream_and_route_blocked" if optional.returncode else "available_route_blocked"
    version = subprocess.run(
        [*runtime_node_command(staging, manifest), "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=30,
    )
    if version.returncode != 0 or version.stdout.strip() != "v24.18.0":
        raise OciImportError("OpenDesign imported Node runtime version changed")
    return {
        "node": version.stdout.strip(),
        "required": {name: "loaded" for name in closure["required_native_modules"]},
        "optional_blocked": optional_status,
    }


def _assert_reproducible(results: list[DerivationResult], asset: dict[str, Any]) -> None:
    if len(results) != 2:
        raise OciImportError("OpenDesign OCI reproducibility requires exactly two imports")
    first, second = results
    if (
        first.artifact_sha256 != second.artifact_sha256
        or first.artifact_size_bytes != second.artifact_size_bytes
        or first.file_manifest_sha256 != second.file_manifest_sha256
        or first.rootfs_inventory_sha256 != second.rootfs_inventory_sha256
        or first.patch_evidence != second.patch_evidence
    ):
        raise OciImportError("OpenDesign independent OCI derivations are not byte-reproducible")
    for path_field in ARTIFACT_DIGEST_FIELDS:
        first_path = first.output_root / asset[path_field]
        second_path = second.output_root / asset[path_field]
        if first_path.read_bytes() != second_path.read_bytes():
            raise OciImportError(f"OpenDesign OCI metadata is not reproducible: {asset[path_field]}")


def _canonical_payload_sha256(payload: Any) -> str:
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _artifact_pins(output_directory: Path, asset: dict[str, Any]) -> dict[str, Any]:
    pins: dict[str, Any] = {"size_bytes": (output_directory / asset["file"]).stat().st_size}
    for path_field, digest_field in ARTIFACT_DIGEST_FIELDS.items():
        pins[digest_field] = sha256_file(output_directory / asset[path_field])
    return pins


def _with_artifact_pins(
    manifest: dict[str, Any],
    pins: dict[str, Any],
) -> dict[str, Any]:
    pinned = copy.deepcopy(manifest)
    selected = pinned["artifact"]["assets"][platform_key()]
    expected = {"size_bytes", *ARTIFACT_DIGEST_FIELDS.values()}
    if set(pins) != expected:
        raise OciImportError("OpenDesign OCI artifact pin set is incomplete")
    selected.update(pins)
    validate_bundle_manifest(pinned, require_artifact_digest=True)
    return pinned


def _publish_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise OciImportError("OpenDesign OCI publish source is unsafe")
    if destination.exists() or destination.is_symlink():
        raise OciImportError("OpenDesign OCI publish destination already exists")
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _real_directory(path: Path, *, create: bool, label: str) -> Path:
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise OciImportError(f"{label} must be a real directory")
    return path.resolve(strict=True)


def _real_file(path: Path, *, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise OciImportError(f"{label} must be a real file")
    return path.resolve(strict=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", type=Path, required=True)
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, default=SERVICE_ROOT / "artifacts")
    parser.add_argument("--work-parent", type=Path, default=Path("/var/tmp"))
    parser.add_argument("--pnpm-store", type=Path, default=SERVICE_ROOT.parents[2] / "tmp/opendesign-pnpm-store")
    parser.add_argument("--allow-operator-detached", action="store_true")
    args = parser.parse_args()
    try:
        with signal_guard():
            runtime_session_id = activate_runtime_attachment(allow_operator_detached=args.allow_operator_detached)
            result = import_reproducible_artifact(
                args.output_directory,
                source_repository=args.source_repository,
                signing_key=args.signing_key,
                manifest=read_bundle_manifest(MANIFEST_PATH),
                work_parent=args.work_parent,
                pnpm_store=args.pnpm_store,
                runtime_session_id=runtime_session_id,
            )
    except (
        ArtifactError,
        BoundaryPatchError,
        OciImportError,
        OciLayoutError,
        OciRegistryError,
        OciStageError,
        SourceError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"OpenDesign OCI import failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
