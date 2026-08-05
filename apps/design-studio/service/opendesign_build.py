"""One clean, frozen, deterministic OpenDesign runtime build."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
from typing import Any

from opendesign_archive import FILE_MANIFEST_PATH, create_file_manifest, write_deterministic_archive
from opendesign_artifact import platform_key, sha256_file, write_canonical_json
from opendesign_attestation import cyclonedx_sbom, license_inventory, notice_text, package_inventory
from opendesign_process import run_command
from opendesign_source import apply_patch_series, export_source
from opendesign_stage import probe_native_dependencies, stage_runtime_closure


class BuildError(RuntimeError):
    """Raised when a clean OpenDesign build violates its frozen inputs."""


@dataclass(frozen=True)
class BuildResult:
    artifact: Path
    artifact_sha256: str
    artifact_size_bytes: int
    file_manifest: dict[str, Any]
    file_manifest_path: Path
    sbom_path: Path
    licenses_path: Path
    notice_path: Path
    build_metadata_path: Path
    source_evidence: dict[str, str]
    patch_evidence: list[dict[str, Any]]
    lockfile_sha256: str


def build_once(
    repository: Path,
    result_root: Path,
    *,
    manifest: dict[str, Any],
    service_root: Path,
    artifact_name: str,
    pnpm_store: Path,
    runtime_session_id: str | None,
) -> BuildResult:
    if not result_root.is_dir() or any(result_root.iterdir()):
        raise BuildError("OpenDesign build result root must be a new empty directory")
    source = result_root / "source"
    staging = result_root / "staging"
    logs = result_root / "logs"
    exported_metadata = result_root / "metadata"
    artifact = result_root / artifact_name
    source_evidence = export_source(repository, source, manifest)
    patch_evidence = apply_patch_series(source, service_root, manifest)
    build = manifest["fallback_build"]["build"]
    lockfile = source / "pnpm-lock.yaml"
    lockfile_sha256 = sha256_file(lockfile)
    tool_bin = result_root / "tool-bin"
    tool_bin.mkdir()
    run_command([*manifest["toolchain"]["corepack_enable"], str(tool_bin)], cwd=source)
    environment = build_environment(
        result_root,
        tool_bin=tool_bin,
        manifest=manifest,
        pnpm_store=pnpm_store,
    )
    verify_toolchain(source, manifest, env=environment)
    run_command(
        build["install"],
        cwd=source,
        env=_phase_environment(environment, build["install_environment"]),
        log_path=logs / "install.log",
        heavy=True,
        runtime_session_id=runtime_session_id,
    )
    _assert_lockfile_unchanged(lockfile, lockfile_sha256, phase="install")
    focused_environment = _phase_environment(
        environment,
        build["focused_verification_environment"],
    )
    for index, command in enumerate(build["focused_verification"], start=1):
        run_command(
            command,
            cwd=source,
            env=focused_environment,
            log_path=logs / f"focused-{index}.log",
            heavy=True,
            runtime_session_id=runtime_session_id,
        )
    compile_environment = _phase_environment(
        environment,
        build["compile_environment"],
    )
    for index, command in enumerate(build["compile"], start=1):
        run_command(
            command,
            cwd=source,
            env=compile_environment,
            log_path=logs / f"compile-{index}.log",
            heavy=True,
            runtime_session_id=runtime_session_id,
        )
    _assert_lockfile_unchanged(lockfile, lockfile_sha256, phase="build")
    normalized_shims = stage_runtime_closure(
        source,
        staging,
        manifest=manifest,
        env=environment,
        runtime_session_id=runtime_session_id,
        log_directory=logs,
    )
    probe_native_dependencies(
        staging,
        manifest,
        env=environment,
        runtime_session_id=runtime_session_id,
        log_path=logs / "native-probe.log",
    )
    packages = package_inventory(staging)
    licenses = license_inventory(packages, upstream=manifest["upstream"])
    metadata_root = staging / "maverick"
    metadata_root.mkdir(parents=True, exist_ok=True)
    write_canonical_json(
        metadata_root / "sbom.cdx.json",
        cyclonedx_sbom(packages, version=manifest["upstream"]["release_version"]),
    )
    write_canonical_json(metadata_root / "licenses.json", licenses)
    (metadata_root / "NOTICE").write_text(notice_text(licenses), encoding="utf-8")
    build_metadata = {
        "schema_version": "1",
        "platform": platform_key(),
        "source": source_evidence,
        "toolchain": manifest["toolchain"],
        "patches": patch_evidence,
        "pnpm_lock_sha256": lockfile_sha256,
        "commands": {
            "install": build["install"],
            "focused_verification": build["focused_verification"],
            "compile": build["compile"],
            "stage": manifest["fallback_build"]["stage"]["daemon_deploy"],
        },
        "normalized_bin_shims": normalized_shims,
    }
    write_canonical_json(metadata_root / "build.json", build_metadata)
    file_manifest = create_file_manifest(staging, exclude={FILE_MANIFEST_PATH})
    write_canonical_json(staging / FILE_MANIFEST_PATH, file_manifest)
    write_deterministic_archive(staging, artifact)
    exported_metadata.mkdir()
    exports = {
        "file-manifest.json": staging / FILE_MANIFEST_PATH,
        "sbom.cdx.json": metadata_root / "sbom.cdx.json",
        "licenses.json": metadata_root / "licenses.json",
        "NOTICE": metadata_root / "NOTICE",
        "build.json": metadata_root / "build.json",
    }
    for name, source_path in exports.items():
        shutil.copy2(source_path, exported_metadata / name)
    return BuildResult(
        artifact=artifact,
        artifact_sha256=sha256_file(artifact),
        artifact_size_bytes=artifact.stat().st_size,
        file_manifest=file_manifest,
        file_manifest_path=exported_metadata / "file-manifest.json",
        sbom_path=exported_metadata / "sbom.cdx.json",
        licenses_path=exported_metadata / "licenses.json",
        notice_path=exported_metadata / "NOTICE",
        build_metadata_path=exported_metadata / "build.json",
        source_evidence=source_evidence,
        patch_evidence=patch_evidence,
        lockfile_sha256=lockfile_sha256,
    )


def build_environment(
    result_root: Path,
    *,
    tool_bin: Path,
    manifest: dict[str, Any],
    pnpm_store: Path,
) -> dict[str, str]:
    build_home = result_root / "home"
    cache_root = build_home / "cache"
    temp_root = build_home / "tmp"
    for path in (build_home, cache_root, temp_root, pnpm_store):
        path.mkdir(parents=True, exist_ok=True)
    if len(os.fsencode(temp_root)) > 72:
        raise BuildError("OpenDesign build TMPDIR is too long for tsx Unix sockets")
    return {
        **manifest["fallback_build"]["build"]["environment"],
        "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
        "COREPACK_HOME": str(cache_root / "corepack"),
        "HOME": str(build_home),
        "PATH": f"{tool_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        "SHELL": "/bin/bash",
        "TERM": "dumb",
        "TMPDIR": str(temp_root),
        "XDG_CACHE_HOME": str(cache_root),
        "XDG_CONFIG_HOME": str(build_home / "config"),
        "XDG_DATA_HOME": str(build_home / "data"),
        "XDG_STATE_HOME": str(build_home / "state"),
        "npm_config_store_dir": str(pnpm_store),
    }


def verify_toolchain(
    source: Path,
    manifest: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
) -> None:
    node = run_command(["node", "--version"], cwd=source, env=env, capture=True).stdout.lstrip("v")
    if node.split(".", 1)[0] != "24":
        raise BuildError(f"OpenDesign build requires Node 24, got {node!r}")
    pnpm = run_command(["corepack", "pnpm", "--version"], cwd=source, env=env, capture=True).stdout
    expected = manifest["toolchain"]["package_manager"].split("@", 1)[1]
    if pnpm != expected:
        raise BuildError(f"OpenDesign build requires pnpm {expected}, got {pnpm!r}")


def _phase_environment(base: dict[str, str], overrides: object) -> dict[str, str]:
    if not isinstance(overrides, dict) or not overrides:
        raise BuildError("OpenDesign phase environment must be a non-empty object")
    if not all(isinstance(key, str) and key and isinstance(value, str) for key, value in overrides.items()):
        raise BuildError("OpenDesign phase environment must contain string keys and values")
    return {**base, **overrides}


def _assert_lockfile_unchanged(lockfile: Path, expected_sha256: str, *, phase: str) -> None:
    if sha256_file(lockfile) != expected_sha256:
        raise BuildError(f"OpenDesign {phase} modified pnpm-lock.yaml")
