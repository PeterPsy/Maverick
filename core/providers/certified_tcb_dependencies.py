"""Static local-import closure audit for the certified execution TCB."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Protocol

from core.providers.errors import CapabilityCertificateError


@dataclass(frozen=True)
class CertifiedTcbDependencyContract:
    """One bounded static-import closure that can alter remote authority/content."""

    contract_id: str
    responsibility: str
    entrypoints: tuple[str, ...]
    follow_module_prefixes: tuple[str, ...]
    required_artifact_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class CertifiedTcbDependencyReport:
    """Deterministic, non-public inventory of audited local import edges."""

    contract_ids: tuple[str, ...]
    audited_paths: tuple[str, ...]
    import_edges: tuple[tuple[str, str], ...]


class CertifiedTcbManifest(Protocol):
    dependency_contracts: tuple[CertifiedTcbDependencyContract, ...]

    @property
    def artifact_paths(self) -> tuple[str, ...]: ...


def audit_certified_tcb_dependencies(
    root: Path,
    *,
    manifest: CertifiedTcbManifest,
) -> CertifiedTcbDependencyReport:
    """Prove that each declared security entrypoint's local import closure is hashed.

    Contracts deliberately follow only security-relevant namespaces, but every
    direct local import reached while following a contract must already be in
    the canonical artifact set. A newly introduced callout therefore fails
    closed until its code and traversal boundary are reviewed together.
    """
    repository_root = root.resolve(strict=True)
    files: dict[str, Path] = {}
    for relative_root in manifest.artifact_paths:
        collect_certified_tcb_manifest_files(repository_root, relative_root, files)
    covered_paths = frozenset(files)
    contract_ids = tuple(contract.contract_id for contract in manifest.dependency_contracts)
    if (
        not contract_ids
        or any(not value for value in contract_ids)
        or len(set(contract_ids)) != len(contract_ids)
    ):
        raise CapabilityCertificateError("certificate_tcb_dependency_contract_invalid")

    audited_paths: set[str] = set()
    import_edges: set[tuple[str, str]] = set()
    for contract in manifest.dependency_contracts:
        _validate_dependency_contract_shape(contract)
        required_paths = (*contract.entrypoints, *contract.required_artifact_paths)
        if any(path not in covered_paths for path in required_paths):
            raise CapabilityCertificateError(
                "certificate_tcb_transitive_dependency_uncovered"
            )
        audited_paths.update(required_paths)
        pending = list(contract.entrypoints)
        visited: set[str] = set()
        while pending:
            source_path = pending.pop(0)
            if source_path in visited:
                continue
            visited.add(source_path)
            source = files.get(source_path)
            if source is None or source.suffix != ".py":
                raise CapabilityCertificateError(
                    "certificate_tcb_dependency_entrypoint_invalid"
                )
            for dependency_path, dependency_module in _local_python_dependencies(
                repository_root,
                source_path,
                source,
            ):
                import_edges.add((source_path, dependency_path))
                if dependency_path not in covered_paths:
                    raise CapabilityCertificateError(
                        "certificate_tcb_transitive_dependency_uncovered"
                    )
                audited_paths.add(dependency_path)
                if _module_matches_prefixes(
                    dependency_module,
                    contract.follow_module_prefixes,
                ):
                    pending.append(dependency_path)

    return CertifiedTcbDependencyReport(
        contract_ids=contract_ids,
        audited_paths=tuple(sorted(audited_paths)),
        import_edges=tuple(sorted(import_edges)),
    )


def collect_certified_tcb_manifest_files(
    repository_root: Path,
    relative_root: str,
    files: dict[str, Path],
) -> None:
    """Collect regular manifest files without following symlinks."""
    if (
        not relative_root
        or relative_root.startswith("/")
        or ".." in Path(relative_root).parts
        or "\x00" in relative_root
    ):
        raise CapabilityCertificateError("certificate_tcb_manifest_path_invalid")
    candidate = repository_root / relative_root
    try:
        candidate.relative_to(repository_root)
        metadata = candidate.lstat()
    except (OSError, ValueError) as error:
        raise CapabilityCertificateError("certificate_tcb_artifact_missing") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise CapabilityCertificateError("certificate_tcb_artifact_symlink")
    if stat.S_ISREG(metadata.st_mode):
        files[candidate.relative_to(repository_root).as_posix()] = candidate
        return
    if not stat.S_ISDIR(metadata.st_mode):
        raise CapabilityCertificateError("certificate_tcb_artifact_invalid")
    for directory, directory_names, file_names in os.walk(candidate, followlinks=False):
        directory_path = Path(directory)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in {"__pycache__", "node_modules", ".git"}
        )
        for name in directory_names:
            if (directory_path / name).is_symlink():
                raise CapabilityCertificateError("certificate_tcb_artifact_symlink")
        for name in sorted(file_names):
            path = directory_path / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise CapabilityCertificateError("certificate_tcb_artifact_symlink")
            if not stat.S_ISREG(metadata.st_mode) or name.endswith((".pyc", ".pyo")):
                continue
            relative = path.relative_to(repository_root).as_posix()
            files[relative] = path


def _validate_dependency_contract_shape(
    contract: CertifiedTcbDependencyContract,
) -> None:
    if (
        not contract.contract_id
        or not contract.responsibility
        or not contract.entrypoints
        or len(set(contract.entrypoints)) != len(contract.entrypoints)
        or len(set(contract.follow_module_prefixes))
        != len(contract.follow_module_prefixes)
        or len(set(contract.required_artifact_paths))
        != len(contract.required_artifact_paths)
        or any(not path.endswith(".py") for path in contract.entrypoints)
        or any(
            not (prefix == "core" or prefix.startswith("core."))
            for prefix in contract.follow_module_prefixes
        )
    ):
        raise CapabilityCertificateError("certificate_tcb_dependency_contract_invalid")


def _local_python_dependencies(
    repository_root: Path,
    source_path: str,
    source: Path,
) -> tuple[tuple[str, str], ...]:
    try:
        tree = ast.parse(
            source.read_text(encoding="utf-8"),
            filename=source_path,
        )
    except (OSError, SyntaxError, UnicodeError) as error:
        raise CapabilityCertificateError(
            "certificate_tcb_dependency_parse_failed"
        ) from error
    source_module = _python_module_name(source_path)
    dependencies: set[tuple[str, str]] = set()
    for module_name in _imported_module_names(
        tree,
        source_module=source_module,
        source_is_package=source_path.endswith("/__init__.py"),
    ):
        resolved = _resolve_local_python_module(repository_root, module_name)
        if resolved is None:
            continue
        dependency_path, dependency_module = resolved
        dependencies.add((dependency_path, dependency_module))
        dependencies.update(
            _package_initializer_dependencies(repository_root, dependency_module)
        )
    return tuple(sorted(dependencies))


def _imported_module_names(
    tree: ast.AST,
    *,
    source_module: str,
    source_is_package: bool,
) -> tuple[str, ...]:
    package = source_module if source_is_package else source_module.rpartition(".")[0]
    modules: set[str] = set()
    for node in ast.walk(tree):
        candidates: list[str] = []
        if isinstance(node, ast.Import):
            candidates.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_from = _absolute_import_from_module(package, node)
            if imported_from:
                candidates.append(imported_from)
                candidates.extend(
                    f"{imported_from}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )
        modules.update(
            name
            for name in candidates
            if name == "core" or name.startswith("core.")
        )
    return tuple(sorted(modules))


def _absolute_import_from_module(package: str, node: ast.ImportFrom) -> str:
    if not node.level:
        return str(node.module or "")
    package_parts = package.split(".") if package else []
    parent_hops = node.level - 1
    if parent_hops > len(package_parts):
        raise CapabilityCertificateError("certificate_tcb_dependency_import_invalid")
    base = package_parts[: len(package_parts) - parent_hops]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _resolve_local_python_module(
    repository_root: Path,
    module_name: str,
) -> tuple[str, str] | None:
    module_path = Path(*module_name.split("."))
    candidates = (
        module_path.with_suffix(".py"),
        module_path / "__init__.py",
    )
    for candidate in candidates:
        if (repository_root / candidate).is_file():
            return candidate.as_posix(), module_name
    return None


def _package_initializer_dependencies(
    repository_root: Path,
    module_name: str,
) -> set[tuple[str, str]]:
    parts = module_name.split(".")
    dependencies: set[tuple[str, str]] = set()
    for length in range(1, len(parts)):
        package_module = ".".join(parts[:length])
        initializer = Path(*parts[:length]) / "__init__.py"
        if (repository_root / initializer).is_file():
            dependencies.add((initializer.as_posix(), package_module))
    return dependencies


def _python_module_name(relative_path: str) -> str:
    path = Path(relative_path)
    if path.name == "__init__.py":
        return ".".join(path.parent.parts)
    return ".".join(path.with_suffix("").parts)


def _module_matches_prefixes(
    module_name: str,
    prefixes: tuple[str, ...],
) -> bool:
    return any(
        module_name == prefix or module_name.startswith(f"{prefix}.")
        for prefix in prefixes
    )
