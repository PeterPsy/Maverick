"""Certified executable closure for hosted built-in app surfaces."""

from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import stat
from typing import Literal

from core.runtime.tool_errors import RuntimeToolError


HostedAppSurface = Literal["cli", "mcp"]
HOSTED_BUILTIN_APP_IDS = (
    "agents",
    "app-store",
    "base-shell",
    "browser",
    "calendar",
    "chat",
    "checklist",
    "crm",
    "design-studio",
    "docs-studio",
    "document-generator",
    "dynamic-views",
    "fitness-coach",
    "mail",
    "memory",
    "senses",
    "settings",
    "skills",
    "speech",
    "storage",
    "vault",
    "video-studio",
    "website-studio",
)
_SURFACE_PATHS = {
    "cli": (Path("cli/app_cli.py"), Path("cli/command_schemas.json")),
    "mcp": (Path("mcp/server.py"), Path("mcp/tool_schemas.json")),
}
_IGNORED_DIRECTORY_NAMES = {".git", "__pycache__", "node_modules"}


def hosted_builtin_app_execution_roots(
    app_id: str,
    *,
    surface: HostedAppSurface,
    apps_root: Path,
) -> tuple[str, ...]:
    """Return the reviewed roots containing every executable app-local byte."""
    if app_id not in HOSTED_BUILTIN_APP_IDS or surface not in _SURFACE_PATHS:
        raise RuntimeToolError("hosted_app_execution_closure_invalid")
    app_root = apps_root / app_id
    entrypoint, descriptor = _SURFACE_PATHS[surface]
    roots = [Path("app_contract.json"), descriptor, entrypoint]
    if (app_root / "backend").is_dir():
        # App entrypoints prepend this directory to sys.path. Treat the whole
        # directory as executable potential, including dynamic local imports.
        roots.append(Path("backend"))
    if app_id == "vault":
        # Vault deliberately imports its single app-root implementation module.
        roots.append(Path("agent_operations.py"))
    if app_id in {"crm", "mail"}:
        # Imported backend read projections load this app-root policy as data.
        # Its fields govern output, so Python-only closure hashing is insufficient.
        roots.append(Path("pwa_read_models.v1.json"))
    if app_id == "design-studio" and surface == "cli":
        # The CLI additionally prepends service/. Its reachable Python closure
        # is explicit so multi-gigabyte release artifacts are never mistaken
        # for executable source authority.
        roots.extend(_design_studio_service_closure(app_root, entrypoint))
    normalized = tuple(sorted({path.as_posix() for path in roots}))
    for relative in normalized:
        _require_regular_file_or_directory(app_root, relative)
    return normalized


def hosted_builtin_app_execution_digest(
    app_id: str,
    *,
    surface: HostedAppSurface,
    apps_root: Path,
) -> str:
    """Hash exact closure paths and bytes without following symlinks."""
    app_root = apps_root / app_id
    files: dict[str, Path] = {}
    for relative_root in hosted_builtin_app_execution_roots(
        app_id,
        surface=surface,
        apps_root=apps_root,
    ):
        _collect_files(app_root, relative_root, files)
    if not files:
        raise RuntimeToolError("hosted_app_execution_closure_invalid")
    digest = hashlib.sha256()
    digest.update(b"maverick.hosted-builtin-app-execution.v1\x00")
    digest.update(app_id.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(surface.encode("ascii"))
    digest.update(b"\x00")
    for relative in sorted(files):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\x00")
        try:
            digest.update(files[relative].read_bytes())
        except OSError as error:
            raise RuntimeToolError("hosted_app_execution_closure_changed") from error
        digest.update(b"\x00")
    return digest.hexdigest()


def certified_hosted_builtin_app_artifact_paths(
    *,
    apps_root: Path,
) -> tuple[str, ...]:
    """Return repository-relative closure roots included in the execution TCB."""
    values: set[str] = set()
    for app_id in HOSTED_BUILTIN_APP_IDS:
        for surface in ("cli", "mcp"):
            for relative in hosted_builtin_app_execution_roots(
                app_id,
                surface=surface,
                apps_root=apps_root,
            ):
                values.add(f"apps/{app_id}/{relative}")
    return tuple(sorted(values))


def _design_studio_service_closure(
    app_root: Path,
    entrypoint: Path,
) -> tuple[Path, ...]:
    backend = app_root / "backend"
    service = app_root / "service"
    search_roots = (backend, service, app_root)
    pending = [app_root / entrypoint]
    if backend.is_dir():
        pending.extend(_regular_python_files(backend))
    visited: set[Path] = set()
    service_files: set[Path] = set()
    while pending:
        source = pending.pop()
        source = source.resolve(strict=True)
        if source in visited:
            continue
        visited.add(source)
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (OSError, SyntaxError, UnicodeError) as error:
            raise RuntimeToolError("hosted_app_execution_closure_invalid") from error
        for module_name in _import_candidates(tree, source=source, roots=search_roots):
            for dependency in _resolve_local_module(module_name, search_roots):
                if dependency not in visited:
                    pending.append(dependency)
                if service == dependency or service in dependency.parents:
                    service_files.add(dependency.relative_to(app_root))
    return tuple(sorted(service_files, key=lambda path: path.as_posix()))


def _import_candidates(
    tree: ast.AST,
    *,
    source: Path,
    roots: tuple[Path, ...],
) -> tuple[str, ...]:
    current_parts: tuple[str, ...] = ()
    source_is_package = source.name == "__init__.py"
    for root in roots:
        try:
            relative = source.relative_to(root)
        except ValueError:
            continue
        current_parts = relative.with_suffix("").parts
        if source_is_package:
            current_parts = current_parts[:-1]
        break
    package_parts = current_parts if source_is_package else current_parts[:-1]
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            hops = node.level - 1
            if hops > len(package_parts):
                raise RuntimeToolError("hosted_app_execution_closure_invalid")
            prefix = list(package_parts[: len(package_parts) - hops])
            if node.module:
                prefix.extend(node.module.split("."))
            base = ".".join(prefix)
        else:
            base = str(node.module or "")
        if base:
            values.add(base)
            values.update(
                f"{base}.{alias.name}"
                for alias in node.names
                if alias.name != "*"
            )
    return tuple(sorted(values))


def _resolve_local_module(
    module_name: str,
    roots: tuple[Path, ...],
) -> tuple[Path, ...]:
    if not module_name or module_name == "core" or module_name.startswith("core."):
        return ()
    module_path = Path(*module_name.split("."))
    resolved: set[Path] = set()
    for root in roots:
        candidates = (root / module_path.with_suffix(".py"), root / module_path / "__init__.py")
        for candidate in candidates:
            try:
                metadata = candidate.lstat()
            except OSError:
                continue
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise RuntimeToolError("hosted_app_execution_closure_invalid")
            resolved.add(candidate.resolve(strict=True))
            relative = candidate.relative_to(root)
            for length in range(1, len(relative.parts) - 1):
                initializer = root.joinpath(*relative.parts[:length], "__init__.py")
                if initializer.is_file():
                    if initializer.is_symlink():
                        raise RuntimeToolError("hosted_app_execution_closure_invalid")
                    resolved.add(initializer.resolve(strict=True))
    return tuple(sorted(resolved, key=lambda path: path.as_posix()))


def _regular_python_files(root: Path) -> tuple[Path, ...]:
    values: list[Path] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        directory_names[:] = sorted(
            name for name in directory_names if name not in _IGNORED_DIRECTORY_NAMES
        )
        for name in directory_names:
            if (directory_path / name).is_symlink():
                raise RuntimeToolError("hosted_app_execution_closure_invalid")
        for name in sorted(file_names):
            path = directory_path / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise RuntimeToolError("hosted_app_execution_closure_invalid")
            if stat.S_ISREG(metadata.st_mode) and path.suffix == ".py":
                values.append(path)
    return tuple(values)


def _collect_files(app_root: Path, relative_root: str, files: dict[str, Path]) -> None:
    candidate = app_root / relative_root
    try:
        candidate.relative_to(app_root)
        metadata = candidate.lstat()
    except (OSError, ValueError) as error:
        raise RuntimeToolError("hosted_app_execution_closure_invalid") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise RuntimeToolError("hosted_app_execution_closure_invalid")
    if stat.S_ISREG(metadata.st_mode):
        files[candidate.relative_to(app_root).as_posix()] = candidate
        return
    if not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeToolError("hosted_app_execution_closure_invalid")
    for path in _regular_manifest_files(candidate):
        files[path.relative_to(app_root).as_posix()] = path


def _regular_manifest_files(root: Path) -> tuple[Path, ...]:
    values: list[Path] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        directory_names[:] = sorted(
            name for name in directory_names if name not in _IGNORED_DIRECTORY_NAMES
        )
        for name in directory_names:
            if (directory_path / name).is_symlink():
                raise RuntimeToolError("hosted_app_execution_closure_invalid")
        for name in sorted(file_names):
            path = directory_path / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise RuntimeToolError("hosted_app_execution_closure_invalid")
            if stat.S_ISREG(metadata.st_mode) and not name.endswith((".pyc", ".pyo")):
                values.append(path)
    return tuple(values)


def _require_regular_file_or_directory(app_root: Path, relative: str) -> None:
    path = app_root / relative
    try:
        metadata = path.lstat()
    except OSError as error:
        raise RuntimeToolError("hosted_app_execution_closure_invalid") from error
    if stat.S_ISLNK(metadata.st_mode) or not (
        stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)
    ):
        raise RuntimeToolError("hosted_app_execution_closure_invalid")


__all__ = [
    "HOSTED_BUILTIN_APP_IDS",
    "certified_hosted_builtin_app_artifact_paths",
    "hosted_builtin_app_execution_digest",
    "hosted_builtin_app_execution_roots",
]
