#!/usr/bin/env python3
"""Build and attest two independent byte-identical OpenDesign runtime artifacts."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Callable
from uuid import uuid4

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
from opendesign_attestation import provenance_payload, sign_provenance, verify_artifact_set
from opendesign_build import BuildResult, build_once
from opendesign_process import BuildProcessError, activate_runtime_attachment, signal_guard
from opendesign_source import SourceError, validate_repository
from opendesign_supply_chain import (
    SupplyChainError,
    validate_certification_record,
    validate_manifest,
    validate_patch_series,
)


SERVICE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = SERVICE_ROOT.parents[2]
MANIFEST_PATH = SERVICE_ROOT / "opendesign_bundle.json"
BuildFunction = Callable[..., BuildResult]


class PackagingError(RuntimeError):
    """Raised when deterministic packaging or publication fails."""


def build_reproducible_artifact(
    repository: Path,
    output_directory: Path,
    *,
    signing_key: Path,
    manifest: dict[str, Any],
    work_parent: Path,
    pnpm_store: Path,
    runtime_session_id: str | None,
    service_root: Path = SERVICE_ROOT,
    build_function: BuildFunction = build_once,
) -> dict[str, Any]:
    validate_manifest(manifest)
    validate_bundle_manifest(manifest, require_artifact_digest=False)
    validate_certification_record(service_root, manifest)
    validate_patch_series(service_root, manifest)
    validate_repository(repository, manifest)
    signing_key = _real_signing_key(signing_key)
    work_parent = _real_directory(work_parent, create=True)
    pnpm_store = _real_directory(pnpm_store, create=True)
    output_directory = _real_directory(output_directory, create=True)
    asset = selected_asset(manifest, require_artifact_digest=False)
    results: list[BuildResult] = []
    with tempfile.TemporaryDirectory(prefix="maverick-opendesign-builds-", dir=work_parent) as temporary:
        temporary_root = Path(temporary)
        for index in (1, 2):
            result_root = temporary_root / f"build-{index}"
            result_root.mkdir()
            results.append(
                build_function(
                    repository,
                    result_root,
                    manifest=manifest,
                    service_root=service_root,
                    artifact_name=asset["file"],
                    pnpm_store=pnpm_store,
                    runtime_session_id=runtime_session_id,
                )
            )
        assert_reproducible(results)
        first = results[0]
        _publish_file(first.artifact, output_directory / asset["file"])
        _publish_file(first.file_manifest_path, output_directory / asset["file_manifest"])
        _publish_file(first.sbom_path, output_directory / asset["sbom"])
        _publish_file(first.licenses_path, output_directory / asset["license_inventory"])
        _publish_file(first.notice_path, output_directory / asset["notice"])
        provenance = provenance_payload(
            artifact_name=asset["file"],
            artifact_sha256=first.artifact_sha256,
            lockfile_sha256=first.lockfile_sha256,
            patch_evidence=first.patch_evidence,
            manifest=manifest,
        )
        provenance_path = output_directory / asset["provenance"]
        write_canonical_json(provenance_path, provenance)
        sign_provenance(
            provenance_path,
            signing_key,
            output_directory / asset["signature"],
            output_directory / asset["public_key"],
        )
    pins = artifact_pins(output_directory, asset)
    pinned_manifest = with_artifact_pins(manifest, pins)
    verify_artifact_set(pinned_manifest, output_directory)
    return {
        "artifact": str(output_directory / asset["file"]),
        "artifact_sha256": pins["sha256"],
        "artifact_size_bytes": pins["size_bytes"],
        "build_artifact_sha256s": [result.artifact_sha256 for result in results],
        "artifact_pins": pins,
        "reproducible_builds": 2,
        "upstream_certification_status": validate_certification_record(service_root, manifest)[
            "latest_acceptance"
        ]["status"],
    }


def assert_reproducible(results: list[BuildResult]) -> None:
    if len(results) != 2:
        raise PackagingError("OpenDesign reproducibility requires exactly two clean builds")
    first, second = results
    if first.artifact_sha256 != second.artifact_sha256 or first.artifact_size_bytes != second.artifact_size_bytes:
        first_files = {item["path"]: item for item in first.file_manifest["files"]}
        second_files = {item["path"]: item for item in second.file_manifest["files"]}
        differing = sorted(
            path
            for path in set(first_files) | set(second_files)
            if first_files.get(path) != second_files.get(path)
        )
        raise PackagingError(
            "OpenDesign clean builds are not byte-identical; differing paths: "
            + ", ".join(differing[:50])
        )
    if first.file_manifest != second.file_manifest:
        raise PackagingError("OpenDesign clean builds produced different file manifests")


def artifact_pins(output_directory: Path, asset: dict[str, Any]) -> dict[str, Any]:
    pins: dict[str, Any] = {"size_bytes": (output_directory / asset["file"]).stat().st_size}
    for path_field, digest_field in ARTIFACT_DIGEST_FIELDS.items():
        pins[digest_field] = sha256_file(output_directory / asset[path_field])
    return pins


def with_artifact_pins(manifest: dict[str, Any], pins: dict[str, Any]) -> dict[str, Any]:
    pinned = copy.deepcopy(manifest)
    asset = pinned["artifact"]["assets"][platform_key()]
    expected = {"size_bytes", *ARTIFACT_DIGEST_FIELDS.values()}
    if set(pins) != expected:
        raise PackagingError("OpenDesign artifact pin result is incomplete")
    asset.update(pins)
    validate_bundle_manifest(pinned, require_artifact_digest=True)
    return pinned


def _publish_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise PackagingError(f"OpenDesign publish source is unsafe: {source.name}")
    if destination.is_symlink():
        raise PackagingError(f"OpenDesign publish destination is a symlink: {destination.name}")
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _real_directory(path: Path, *, create: bool) -> Path:
    path = Path(path)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise PackagingError(f"OpenDesign directory is unsafe: {path}")
    return path.resolve(strict=True)


def _real_signing_key(path: Path) -> Path:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise PackagingError("OpenDesign provenance signing key must be a real file")
    return path.resolve(strict=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", type=Path, required=True)
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, default=SERVICE_ROOT / "artifacts")
    parser.add_argument("--work-parent", type=Path, default=Path("/var/tmp"))
    parser.add_argument("--pnpm-store", type=Path, default=REPOSITORY_ROOT / "tmp/opendesign-pnpm-store")
    parser.add_argument("--allow-operator-detached", action="store_true")
    args = parser.parse_args()
    try:
        with signal_guard():
            runtime_session_id = activate_runtime_attachment(
                allow_operator_detached=args.allow_operator_detached
            )
            manifest = read_bundle_manifest(MANIFEST_PATH)
            result = build_reproducible_artifact(
                args.source_repository,
                args.output_directory,
                signing_key=args.signing_key,
                manifest=manifest,
                work_parent=args.work_parent,
                pnpm_store=args.pnpm_store,
                runtime_session_id=runtime_session_id,
            )
    except (
        ArtifactError,
        BuildProcessError,
        OSError,
        PackagingError,
        SourceError,
        SupplyChainError,
    ) as exc:
        print(f"OpenDesign packaging failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
