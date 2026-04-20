"""Workspace-only process launcher for sandboxed runtime backends."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil


SYSTEM_READ_ROOTS = ("/usr", "/bin", "/lib", "/lib64", "/etc")
SYSTEM_READ_PATHS = tuple(Path(root) for root in SYSTEM_READ_ROOTS)
MASKED_SYSTEM_PATHS = (
    "/usr/share",
    "/usr/local/share",
)
RESOLV_CONF = Path("/etc/resolv.conf")


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
    dependencies = _dedupe_paths([path.resolve(strict=False) for path in dependency_roots or [] if path.exists()])
    file_dependencies = [(source.resolve(strict=False), destination.resolve(strict=False)) for source, destination in dependency_files or [] if source.exists()]
    resolver_roots = _resolver_read_roots()
    system_roots = _system_read_roots(resolver_roots)
    args = [
        _require_bwrap(),
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--tmpfs",
        "/",
        "--setenv",
        "TMPDIR",
        str(runtime),
        "--setenv",
        "TMP",
        str(runtime),
        "--setenv",
        "TEMP",
        str(runtime),
        "--setenv",
        "HOME",
        str(runtime / "codex-home"),
        "--unsetenv",
        "PYTHONPATH",
    ]
    exposed_paths = [workspace, runtime, *dependencies]
    mount_dirs = _dedupe_paths([Path("/proc"), Path("/dev"), *_mount_parent_dirs([*system_roots, *exposed_paths])])
    for directory in mount_dirs:
        args.extend(["--dir", str(directory)])
    args.extend(["--proc", "/proc", "--dev", "/dev"])
    for root in system_roots:
        args.extend(["--ro-bind", str(root), str(root)])
    for dependency in dependencies:
        args.extend(["--ro-bind", str(dependency), str(dependency)])
    for path in _masked_system_paths():
        args.extend(["--tmpfs", str(path)])
    args.extend(["--bind", str(workspace), str(workspace)])
    if runtime.is_relative_to(workspace):
        (workspace / runtime.relative_to(workspace)).mkdir(parents=True, exist_ok=True)
    else:
        runtime.mkdir(parents=True, exist_ok=True)
        args.extend(["--bind", str(runtime), str(runtime)])
    for source, destination in file_dependencies:
        destination.parent.mkdir(parents=True, exist_ok=True)
        args.extend(["--ro-bind", str(source), str(destination)])
    if not workspace.is_relative_to("/tmp"):
        args.extend(["--dir", "/tmp", "--bind", str(runtime), "/tmp"])
    args.extend(["--remount-ro", "/", "--chdir", str(workspace), "--"])
    args.extend(command)
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


def _system_read_roots(extra_roots: list[Path] | None = None) -> list[Path]:
    roots = [Path(root) for root in SYSTEM_READ_ROOTS if Path(root).exists()]
    roots.extend(path for path in extra_roots or [] if path.exists())
    return _dedupe_paths(roots)


def _masked_system_paths() -> list[Path]:
    return [Path(path) for path in MASKED_SYSTEM_PATHS if Path(path).exists()]


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
