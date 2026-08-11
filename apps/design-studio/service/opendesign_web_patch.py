"""Build and overlay the pinned, source-patched OpenDesign web application."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from opendesign_archive import create_file_manifest
from opendesign_artifact import sha256_file
from opendesign_build import build_environment, verify_toolchain
from opendesign_process import run_command
from opendesign_source import SourceError, apply_patch_series, export_source


class WebPatchError(RuntimeError):
    """Raised when the reviewed React patch cannot produce the authorized web overlay."""


def build_and_overlay_web(
    repository: Path,
    rootfs: Path,
    result_root: Path,
    *,
    manifest: dict[str, Any],
    service_root: Path,
    pnpm_store: Path,
    runtime_session_id: str | None,
) -> dict[str, Any]:
    source = result_root / "source"
    logs = result_root / "logs"
    tool_bin = result_root / "tool-bin"
    tool_bin.mkdir(parents=True)
    source_evidence = export_source(repository, source, manifest)
    patch_evidence = apply_patch_series(source, service_root, manifest)
    lockfile = source / "pnpm-lock.yaml"
    lockfile_sha256 = sha256_file(lockfile)
    run_command([*manifest["toolchain"]["corepack_enable"], str(tool_bin)], cwd=source)
    environment = build_environment(
        result_root,
        tool_bin=tool_bin,
        manifest=manifest,
        pnpm_store=pnpm_store,
    )
    verify_toolchain(source, manifest, env=environment)
    build = manifest["fallback_build"]["build"]
    install_environment = {**environment, **build["install_environment"]}
    compile_environment = {**environment, **build["compile_environment"]}
    run_command(
        build["install"],
        cwd=source,
        env=install_environment,
        log_path=logs / "install.log",
        heavy=True,
        runtime_session_id=runtime_session_id,
    )
    if sha256_file(lockfile) != lockfile_sha256:
        raise WebPatchError("OpenDesign web install modified pnpm-lock.yaml")
    web_commands = [
        command
        for command in build["compile"]
        if isinstance(command, list) and "@open-design/web" in command
    ]
    if len(web_commands) != 1:
        raise WebPatchError("OpenDesign web build command is missing or ambiguous")
    run_command(
        web_commands[0],
        cwd=source,
        env=compile_environment,
        log_path=logs / "web-build.log",
        heavy=True,
        runtime_session_id=runtime_session_id,
    )
    if sha256_file(lockfile) != lockfile_sha256:
        raise WebPatchError("OpenDesign web build modified pnpm-lock.yaml")
    source_output = source / "apps/web/out"
    if source_output.is_symlink() or not source_output.is_dir():
        raise WebPatchError("OpenDesign patched static web output is missing")
    for source_map in source_output.rglob("*.map"):
        if source_map.is_file() or source_map.is_symlink():
            source_map.unlink()
    target = rootfs / manifest["web_patch"]["output_path"]
    try:
        target.resolve(strict=True).relative_to(rootfs.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise WebPatchError("OpenDesign web overlay target is unsafe") from exc
    if target.is_symlink() or not target.is_dir():
        raise WebPatchError("OpenDesign OCI web preimage is missing")
    shutil.rmtree(target)
    shutil.copytree(source_output, target, symlinks=True)
    output_inventory = create_file_manifest(target)
    output_sha256 = hashlib.sha256(
        (json.dumps(output_inventory, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    ).hexdigest()
    expected_output = manifest["web_patch"].get("output_manifest_sha256")
    if expected_output is not None and output_sha256 != expected_output:
        raise WebPatchError("OpenDesign patched web output does not match its manifest pin")
    return {
        "output_path": manifest["web_patch"]["output_path"],
        "output_manifest_sha256": output_sha256,
        "source": source_evidence,
        "patches": patch_evidence,
        "pnpm_lock_sha256": lockfile_sha256,
        "capabilities": manifest["web_patch"]["capabilities"],
    }


__all__ = ["SourceError", "WebPatchError", "build_and_overlay_web"]
