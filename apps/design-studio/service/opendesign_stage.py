"""Create and validate the relocatable OpenDesign runtime closure."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Any, Iterator
from uuid import uuid4

from opendesign_archive import artifact_paths, create_file_manifest
from opendesign_process import run_command


class StageError(RuntimeError):
    """Raised when the runtime closure is incomplete or build-path dependent."""


def stage_runtime_closure(
    source: Path,
    staging: Path,
    *,
    manifest: dict[str, Any],
    env: dict[str, str],
    runtime_session_id: str | None,
    log_directory: Path,
) -> list[str]:
    if staging.exists() or staging.is_symlink():
        raise StageError("OpenDesign staging destination must not exist")
    stage = manifest["stage"]
    daemon_root = staging / "apps/daemon"
    daemon_root.parent.mkdir(parents=True)
    run_command(
        [*stage["daemon_deploy"], str(daemon_root)],
        cwd=source,
        env=env,
        log_path=log_directory / "deploy.log",
        heavy=True,
        runtime_session_id=runtime_session_id,
    )
    web_source = _safe_source(source, stage["web_static_source"])
    if web_source.is_symlink() or not web_source.is_dir():
        raise StageError("OpenDesign web static export is missing after build")
    web_destination = staging.joinpath(*PurePosixPath(stage["web_static_dir"]).parts)
    web_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(web_source, web_destination, symlinks=True)
    for relative in stage["resource_paths"]:
        source_path = _safe_source(source, relative)
        destination = staging.joinpath(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_dir() and not source_path.is_symlink():
            shutil.copytree(source_path, destination, symlinks=True)
        elif source_path.is_file() and not source_path.is_symlink():
            shutil.copy2(source_path, destination)
        else:
            raise StageError(f"OpenDesign approved runtime content is unsafe: {relative}")
    shutil.copy2(_safe_source(source, "LICENSE"), staging / "LICENSE")
    for source_map in artifact_paths(staging):
        if source_map.name.endswith(".map") and (source_map.is_file() or source_map.is_symlink()):
            source_map.unlink()
    for metadata in (
        daemon_root / "node_modules/.modules.yaml",
        daemon_root / "node_modules/.pnpm/lock.yaml",
        daemon_root / "node_modules/.pnpm-workspace-state-v1.json",
    ):
        metadata.unlink(missing_ok=True)
    _remove_daemon_self_link(daemon_root, source / "apps/daemon")
    normalized = _normalize_bin_shims(staging, daemon_root)
    required = [
        staging.joinpath(*PurePosixPath(stage["built_entrypoint"]).parts),
        web_destination,
    ]
    if any(not path.exists() for path in required):
        raise StageError("OpenDesign staged closure is missing daemon or web output")
    create_file_manifest(staging)
    _reject_build_path_leaks(staging, markers=(str(source), str(staging.parent)))
    return normalized


def probe_native_dependencies(
    staging: Path,
    manifest: dict[str, Any],
    *,
    env: dict[str, str],
    runtime_session_id: str | None,
    log_path: Path,
) -> None:
    modules = manifest["native_runtime_dependencies"]
    script = "for (const name of JSON.parse(process.argv[1])) { require(name); console.log(name + ':ok'); }"
    run_command(
        ["node", "-e", script, json.dumps(modules)],
        cwd=staging / "apps/daemon",
        env=env,
        log_path=log_path,
        heavy=True,
        runtime_session_id=runtime_session_id,
    )


def _remove_daemon_self_link(daemon_root: Path, source_daemon_root: Path) -> None:
    self_link = daemon_root / "node_modules/.pnpm/node_modules/@open-design/daemon"
    if not self_link.is_symlink():
        raise StageError("OpenDesign deploy closure is missing its expected daemon source self-link")
    try:
        actual = self_link.resolve(strict=True)
        expected = source_daemon_root.resolve(strict=True)
    except FileNotFoundError as exc:
        raise StageError("OpenDesign deploy daemon self-link is dangling") from exc
    if actual != expected:
        raise StageError("OpenDesign deploy daemon self-link has an unexpected target")
    self_link.unlink()


def _normalize_bin_shims(staging: Path, daemon_root: Path) -> list[str]:
    staging = staging.resolve(strict=True)
    staging_text = str(staging)
    build_marker = str(staging.parent).encode("utf-8")
    normalized: list[str] = []
    for shim in sorted((daemon_root / "node_modules").glob("**/.bin/*")):
        if shim.is_symlink() or not shim.is_file():
            continue
        payload = shim.read_bytes()
        if staging_text.encode("utf-8") not in payload:
            continue
        try:
            source = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StageError(f"OpenDesign deploy bin shim is not UTF-8: {shim.name}") from exc
        leaking_lines = [line for line in source.splitlines() if staging_text in line]
        if (
            not source.startswith("#!/bin/sh\n")
            or "basedir=" not in source
            or not leaking_lines
            or any(not line.startswith('  export NODE_PATH="') for line in leaking_lines)
        ):
            raise StageError(f"OpenDesign build path appeared in an unexpected shim: {shim.name}")
        relative_staging = os.path.relpath(staging, shim.parent.resolve(strict=True)).replace(os.sep, "/")
        replacement = "$basedir" if relative_staging == "." else f"$basedir/{relative_staging}"
        rewritten = source.replace(staging_text, replacement).encode("utf-8")
        if build_marker in rewritten:
            raise StageError(f"OpenDesign bin shim retains its build root: {shim.name}")
        mode = shim.stat().st_mode & 0o7777
        temporary = shim.with_name(f".{shim.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(rewritten)
            temporary.chmod(mode)
            os.replace(temporary, shim)
        finally:
            temporary.unlink(missing_ok=True)
        normalized.append(shim.relative_to(staging).as_posix())
    return normalized


def _reject_build_path_leaks(staging: Path, *, markers: tuple[str, ...]) -> None:
    encoded_markers = tuple(marker.encode("utf-8") for marker in markers if marker)
    for path in artifact_paths(staging):
        if path.is_symlink():
            payloads = [os.readlink(path).encode("utf-8")]
        elif path.is_file():
            payloads = _file_chunks(path)
        else:
            continue
        if any(marker in payload for payload in payloads for marker in encoded_markers):
            relative = path.relative_to(staging).as_posix()
            raise StageError(f"OpenDesign staged closure retains a build path: {relative}")


def _file_chunks(path: Path, *, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    with path.open("rb") as handle:
        tail = b""
        while chunk := handle.read(chunk_size):
            yield tail + chunk
            tail = chunk[-4096:]


def _safe_source(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise StageError(f"unsafe OpenDesign staging path: {relative}")
    candidate = root.joinpath(*path.parts)
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise StageError(f"OpenDesign staging source escapes its root: {relative}") from exc
    return candidate
