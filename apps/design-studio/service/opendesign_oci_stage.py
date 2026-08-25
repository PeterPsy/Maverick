"""Select and normalize the OpenDesign OCI runtime closure."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
from typing import Any

from opendesign_archive import artifact_paths
from opendesign_artifact import sha256_file


class OciStageError(RuntimeError):
    """Fail-closed OCI runtime-closure staging error."""


_DAEMON_BOOTSTRAP = """\
import { enableCompileCache, flushCompileCache } from 'node:module';
const cacheDir = process.env.MAVERICK_OPENDESIGN_NODE_COMPILE_CACHE;
if (cacheDir) {
  enableCompileCache(cacheDir);
  delete process.env.MAVERICK_OPENDESIGN_NODE_COMPILE_CACHE;
}
await import(process.argv[1]);
if (cacheDir) flushCompileCache();
"""


def stage_runtime_closure(
    rootfs: Path,
    staging: Path,
    *,
    manifest: dict[str, Any],
    service_root: Path,
) -> None:
    if rootfs.is_symlink() or not rootfs.is_dir():
        raise OciStageError("OpenDesign OCI rootfs must be a real directory")
    if staging.exists() or staging.is_symlink():
        raise OciStageError("OpenDesign OCI staging destination must not exist")
    staging.mkdir(parents=True, mode=0o755)
    try:
        _copy_tree(_required_rootfs_path(rootfs, "app", directory=True), staging / "app")
        embedded_web = staging / "app/apps/web/out"
        if embedded_web.is_symlink():
            raise OciStageError("OpenDesign embedded web output must not be a symlink")
        if embedded_web.exists():
            shutil.rmtree(embedded_web)
        node = _required_rootfs_path(rootfs, "usr/local/bin/node", directory=False)
        node_destination = staging / "runtime/bin/node"
        node_destination.parent.mkdir(parents=True)
        shutil.copy2(node, node_destination, follow_symlinks=False)
        _copy_tree(_required_rootfs_path(rootfs, "lib", directory=True), staging / "runtime/lib")
        _copy_tree(_required_rootfs_path(rootfs, "usr/lib", directory=True), staging / "runtime/usr-lib")
        upstream_license = manifest["upstream_license"]
        license_path = service_root.joinpath(*upstream_license["path"].split("/"))
        if license_path.is_symlink() or not license_path.is_file():
            raise OciStageError("OpenDesign pinned upstream license is missing")
        if sha256_file(license_path) != upstream_license["sha256"]:
            raise OciStageError("OpenDesign pinned upstream license digest changed")
        shutil.copy2(license_path, staging / "LICENSE")
        node_license = _required_rootfs_path(rootfs, "usr/local/LICENSE", directory=False)
        licenses = staging / "LICENSES"
        licenses.mkdir()
        shutil.copy2(node_license, licenses / "node-runtime.txt")
        _normalize_tree(staging)
        _verify_closure(staging, manifest)
    except Exception:
        shutil.rmtree(staging)
        raise


def runtime_command(bundle_root: Path, manifest: dict[str, Any]) -> list[str]:
    entrypoint = _safe_stage_path(
        bundle_root,
        manifest["runtime_closure"]["daemon_entrypoint"],
        directory=False,
    )
    return [
        *runtime_node_command(bundle_root, manifest),
        "--input-type=module",
        "--eval",
        _DAEMON_BOOTSTRAP,
        entrypoint.as_uri(),
        "--no-open",
    ]


def runtime_node_command(bundle_root: Path, manifest: dict[str, Any]) -> list[str]:
    closure = manifest["runtime_closure"]
    loader = _safe_stage_path(bundle_root, closure["musl_loader"], directory=False)
    node = _safe_stage_path(bundle_root, closure["node"], directory=False)
    libraries = [str(_safe_stage_path(bundle_root, value, directory=True)) for value in closure["library_paths"]]
    return [
        str(loader),
        "--library-path",
        ":".join(libraries),
        str(node),
    ]


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, symlinks=True)


def _required_rootfs_path(rootfs: Path, relative: str, *, directory: bool) -> Path:
    candidate = rootfs.joinpath(*relative.split("/"))
    try:
        candidate.resolve(strict=True).relative_to(rootfs.resolve(strict=True))
        mode = candidate.lstat().st_mode
    except (OSError, ValueError) as exc:
        raise OciStageError(f"OpenDesign OCI runtime path is missing or unsafe: {relative}") from exc
    if stat.S_ISLNK(mode) or (directory and not stat.S_ISDIR(mode)) or (not directory and not stat.S_ISREG(mode)):
        raise OciStageError(f"OpenDesign OCI runtime path has the wrong type: {relative}")
    return candidate


def _safe_stage_path(root: Path, relative: str, *, directory: bool) -> Path:
    candidate = root.joinpath(*relative.split("/"))
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
        mode = candidate.lstat().st_mode
    except (OSError, ValueError) as exc:
        raise OciStageError(f"OpenDesign runtime closure path is missing or unsafe: {relative}") from exc
    if stat.S_ISLNK(mode) or (directory and not stat.S_ISDIR(mode)) or (not directory and not stat.S_ISREG(mode)):
        raise OciStageError(f"OpenDesign runtime closure path has the wrong type: {relative}")
    return candidate


def _normalize_tree(root: Path) -> None:
    # A staging root created below a collaborative/setgid work directory may
    # inherit 02000.  Clear it before later metadata directories are created,
    # otherwise identical inputs produce environment-dependent tar headers.
    root.chmod(0o755)
    for path in artifact_paths(root):
        if path.is_symlink():
            try:
                os.utime(path, (0, 0), follow_symlinks=False)
            except (NotImplementedError, OSError):
                pass
            continue
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            path.chmod(0o755)
        elif stat.S_ISREG(mode):
            path.chmod(0o755 if mode & 0o111 else 0o644)
        else:
            raise OciStageError("OpenDesign runtime closure contains an unsupported object")
        os.utime(path, (0, 0), follow_symlinks=False)
    root.chmod(0o755)
    os.utime(root, (0, 0), follow_symlinks=False)


def _verify_closure(staging: Path, manifest: dict[str, Any]) -> None:
    runtime_command(staging, manifest)
    daemon_root = staging / "app/apps/daemon"
    package_json = daemon_root / "package.json"
    node_modules = daemon_root / "node_modules"
    if package_json.is_symlink() or not package_json.is_file() or node_modules.is_symlink() or not node_modules.is_dir():
        raise OciStageError("OpenDesign OCI closure is missing the compiled daemon dependencies")
    server = staging.joinpath(*manifest["boundary_patch"]["path"].split("/"))
    if sha256_file(server) != manifest["boundary_patch"]["post_sha256"]:
        raise OciStageError("OpenDesign OCI closure does not contain the pinned boundary patch")
    bundled = staging.joinpath(*manifest["startup_patch"]["path"].split("/"))
    if sha256_file(bundled) != manifest["startup_patch"]["post_sha256"]:
        raise OciStageError("OpenDesign OCI closure does not contain the pinned startup patch")
    if (staging / "app/apps/web/out").exists():
        raise OciStageError("OpenDesign runtime closure must not contain embedded web output")


__all__ = ["OciStageError", "runtime_command", "runtime_node_command", "stage_runtime_closure"]
