"""Workspace-only process launcher for sandboxed runtime backends."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil


SYSTEM_READ_ROOTS: tuple[str, ...] = ()
SYSTEM_READ_PATHS = tuple(Path(root) for root in SYSTEM_READ_ROOTS)
MASKED_SYSTEM_PATHS = (
    "/usr/share",
    "/usr/local/share",
)
RESOLV_CONF = Path("/etc/resolv.conf")
SANDBOX_WORKSPACE_ROOT = Path("/workspace")
SANDBOX_EXTERNAL_RUNTIME_ROOT = Path("/runtime")
ESSENTIAL_READ_FILES = (
    (Path("/etc/resolv.conf"), Path("/etc/resolv.conf")),
    (Path("/etc/hosts"), Path("/etc/hosts")),
    (Path("/etc/nsswitch.conf"), Path("/etc/nsswitch.conf")),
    (Path("/etc/ssl/certs/ca-certificates.crt"), Path("/etc/ssl/certs/ca-certificates.crt")),
    (Path("/etc/ssl/cert.pem"), Path("/etc/ssl/cert.pem")),
    (Path("/etc/pki/tls/certs/ca-bundle.crt"), Path("/etc/pki/tls/certs/ca-bundle.crt")),
)


def build_bwrap_command(
    *,
    workspace_root: Path,
    runtime_root: Path,
    dependency_roots: list[Path] | None,
    dependency_files: list[tuple[Path, Path]] | None = None,
    command: list[str],
) -> list[str]:
    """Build a bubblewrap command that exposes only runtime dependencies and the workspace."""
    if not command:
        raise ValueError("workspace sandbox requires a command to execute")
    workspace = workspace_root.resolve(strict=False)
    runtime = runtime_root.resolve(strict=False)
    sandbox_workspace = SANDBOX_WORKSPACE_ROOT
    sandbox_runtime = _sandbox_runtime_path(workspace=workspace, runtime=runtime)
    dependencies = _dedupe_paths([path for path in dependency_roots or [] if path.exists()])
    file_dependencies = [
        (source.resolve(strict=False), _sandbox_destination_path(destination, workspace=workspace, sandbox_workspace=sandbox_workspace, runtime=runtime, sandbox_runtime=sandbox_runtime))
        for source, destination in dependency_files or []
        if source.exists()
    ]
    essential_files = _essential_read_files()
    all_file_dependencies = _dedupe_file_dependencies([*essential_files, *file_dependencies])
    args = [
        _require_bwrap(),
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--tmpfs",
        "/",
        "--setenv",
        "TMPDIR",
        str(sandbox_runtime),
        "--setenv",
        "TMP",
        str(sandbox_runtime),
        "--setenv",
        "TEMP",
        str(sandbox_runtime),
        "--setenv",
        "HOME",
        str(sandbox_runtime / "codex-home"),
        "--setenv",
        "CODEX_HOME",
        str(sandbox_runtime / "codex-home"),
        "--setenv",
        "MAVERICK_WORKSPACE_ROOT",
        str(sandbox_workspace),
        "--setenv",
        "MAVERICK_RUNTIME_ROOT",
        str(sandbox_runtime),
        "--setenv",
        "PATH",
        _sandbox_path_env(workspace=workspace, sandbox_workspace=sandbox_workspace, runtime=runtime, sandbox_runtime=sandbox_runtime),
        "--unsetenv",
        "PYTHONPATH",
    ]
    dependency_destinations = dependencies
    exposed_paths = [sandbox_workspace, sandbox_runtime, *dependency_destinations]
    file_destination_dirs = [destination.parent for _source, destination in all_file_dependencies]
    mount_dirs = _dedupe_paths([Path("/proc"), Path("/dev"), *_mount_parent_dirs([*exposed_paths, *file_destination_dirs])])
    for directory in mount_dirs:
        args.extend(["--dir", str(directory)])
    args.extend(["--proc", "/proc", "--dev", "/dev"])
    for dependency in dependencies:
        args.extend(["--ro-bind", str(dependency), str(dependency)])
    for path in _masked_system_paths(mount_dirs):
        args.extend(["--tmpfs", str(path)])
    args.extend(["--bind", str(workspace), str(sandbox_workspace)])
    if runtime.is_relative_to(workspace):
        (workspace / runtime.relative_to(workspace)).mkdir(parents=True, exist_ok=True)
    else:
        runtime.mkdir(parents=True, exist_ok=True)
        args.extend(["--bind", str(runtime), str(sandbox_runtime)])
    for source, destination in all_file_dependencies:
        args.extend(["--ro-bind", str(source), str(destination)])
    args.extend(["--remount-ro", "/", "--chdir", str(sandbox_workspace), "--"])
    args.extend(_sandbox_command(command, workspace=workspace, sandbox_workspace=sandbox_workspace, runtime=runtime, sandbox_runtime=sandbox_runtime))
    return args


def main(argv: list[str] | None = None) -> int:
    """Exec the requested command inside the workspace sandbox."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--dependency-root", action="append", default=[])
    parser.add_argument("--dependency-file", action="append", default=[])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    bwrap_command = build_bwrap_command(
        workspace_root=Path(args.workspace_root),
        runtime_root=Path(args.runtime_root),
        dependency_roots=[Path(root) for root in args.dependency_root],
        dependency_files=_parse_dependency_files(args.dependency_file),
        command=command,
    )
    os.execvp(bwrap_command[0], bwrap_command)
    return 127


def _require_bwrap() -> str:
    resolved = shutil.which("bwrap")
    if not resolved:
        raise RuntimeError("Sandbox runtime requires bubblewrap (`bwrap`) for workspace read/write confinement.")
    return resolved


def _parse_dependency_files(values: list[str]) -> list[tuple[Path, Path]]:
    files: list[tuple[Path, Path]] = []
    for value in values:
        source, separator, destination = value.partition("=")
        if not separator or not source or not destination:
            raise ValueError("dependency files must use SOURCE=DESTINATION")
        files.append((Path(source), Path(destination)))
    return files



def _sandbox_runtime_path(*, workspace: Path, runtime: Path) -> Path:
    if runtime.is_relative_to(workspace):
        return SANDBOX_WORKSPACE_ROOT / runtime.relative_to(workspace)
    return SANDBOX_EXTERNAL_RUNTIME_ROOT



def _sandbox_destination_path(path: Path, *, workspace: Path, sandbox_workspace: Path, runtime: Path, sandbox_runtime: Path) -> Path:
    resolved = path if path.is_absolute() else path.resolve(strict=False)
    if resolved.is_relative_to(workspace):
        return sandbox_workspace / resolved.relative_to(workspace)
    if resolved.is_relative_to(runtime):
        return sandbox_runtime / resolved.relative_to(runtime)
    if path.is_absolute():
        return path
    return resolved



def _sandbox_command(command: list[str], *, workspace: Path, sandbox_workspace: Path, runtime: Path, sandbox_runtime: Path) -> list[str]:
    return [_sandbox_arg(value, workspace=workspace, sandbox_workspace=sandbox_workspace, runtime=runtime, sandbox_runtime=sandbox_runtime) for value in command]



def _sandbox_arg(value: str, *, workspace: Path, sandbox_workspace: Path, runtime: Path, sandbox_runtime: Path) -> str:
    if not value.startswith("/"):
        return value
    path = Path(value)
    if path.is_relative_to(workspace):
        return str(sandbox_workspace / path.relative_to(workspace))
    if path.is_relative_to(runtime):
        return str(sandbox_runtime / path.relative_to(runtime))
    return value



def _sandbox_path_env(*, workspace: Path, sandbox_workspace: Path, runtime: Path, sandbox_runtime: Path) -> str:
    entries = [str(sandbox_runtime / "bin")]
    for entry in str(os.environ.get("PATH") or "").split(os.pathsep):
        if not entry:
            continue
        entries.append(_sandbox_arg(entry, workspace=workspace, sandbox_workspace=sandbox_workspace, runtime=runtime, sandbox_runtime=sandbox_runtime))
    return os.pathsep.join(entries)


def _masked_system_paths(mount_dirs: list[Path]) -> list[Path]:
    mounted = {str(path) for path in mount_dirs}
    return [
        Path(path)
        for path in MASKED_SYSTEM_PATHS
        if Path(path).exists() and str(Path(path).parent) in mounted
    ]


def _resolver_read_roots(resolv_conf: Path = RESOLV_CONF) -> list[Path]:
    try:
        target = resolv_conf.resolve(strict=True)
    except OSError:
        return []
    if target == resolv_conf or _is_system_read_path(target):
        return []
    if target.is_file():
        return [target.parent]
    return [target]


def _mount_parent_dirs(paths: list[Path]) -> list[Path]:
    parents: list[Path] = []
    for path in paths:
        current = path.parent
        chain: list[Path] = []
        while str(current) not in {"", "/"}:
            chain.append(current)
            current = current.parent
        parents.extend(reversed(chain))
        if path.is_dir() or not path.exists():
            parents.append(path)
    return _dedupe_paths(parents)


def _is_system_read_path(path: Path) -> bool:
    return any(path == root or path.is_relative_to(root) for root in SYSTEM_READ_PATHS)


def _essential_read_files() -> list[tuple[Path, Path]]:
    files: list[tuple[Path, Path]] = []
    for source, destination in ESSENTIAL_READ_FILES:
        try:
            resolved = source.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file():
            files.append((resolved, destination))
    return _dedupe_file_dependencies(files)


def _dedupe_file_dependencies(paths: list[tuple[Path, Path]]) -> list[tuple[Path, Path]]:
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[Path, Path]] = []
    for source, destination in paths:
        key = (str(source), str(destination))
        if key in seen:
            continue
        seen.add(key)
        unique.append((source, destination))
    return unique


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        value = str(path)
        if value in seen:
            continue
        seen.add(value)
        unique.append(path)
    return unique


if __name__ == "__main__":
    raise SystemExit(main())
