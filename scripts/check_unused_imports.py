#!/usr/bin/env python3
"""Fail when Python files contain unused top-level imports.

This is intentionally small and dependency-free. It is not a full linter; it
only catches the stale-import class of issues that `compileall` cannot see.
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys


DEFAULT_ROOTS = ("core", "tests", "apps", "scripts")


class UsageCollector(ast.NodeVisitor):
    """Collect runtime names and names listed in module-level __all__."""

    def __init__(self) -> None:
        self.used: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        return

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        return

    def visit_Name(self, node: ast.Name) -> None:
        self.used.add(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.visit(node.value)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                self._collect_all_names(node.value)
        self.generic_visit(node)

    def _collect_all_names(self, value: ast.AST) -> None:
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            for item in value.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    self.used.add(item.value)


def imported_local_name(alias: ast.alias, *, module_import: bool) -> str:
    if alias.asname:
        return alias.asname
    if module_import:
        return alias.name.split(".", 1)[0]
    return alias.name


def unused_imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    type_checking_lines = imports_under_type_checking(tree)
    collector = UsageCollector()
    collector.visit(tree)
    used = collector.used
    findings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if node.lineno in type_checking_lines:
                continue
            for alias in node.names:
                local_name = imported_local_name(alias, module_import=True)
                if local_name not in used:
                    findings.append((node.lineno, local_name))
        elif isinstance(node, ast.ImportFrom):
            if node.lineno in type_checking_lines:
                continue
            if node.module == "__future__":
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = imported_local_name(alias, module_import=False)
                if local_name not in used:
                    findings.append((node.lineno, local_name))
    return sorted(findings)


def imports_under_type_checking(tree: ast.AST) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if not isinstance(node.test, ast.Name) or node.test.id != "TYPE_CHECKING":
            continue
        for child in ast.walk(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                lines.add(child.lineno)
    return lines


def python_files(paths: list[str]) -> list[Path]:
    roots = paths or list(DEFAULT_ROOTS)
    files: list[Path] = []
    for root in roots:
        path = Path(root)
        if path.is_file() and path.suffix == ".py":
            files.append(path)
        elif path.is_dir():
            files.extend(
                item
                for item in path.rglob("*.py")
                if "__pycache__" not in item.parts and ".venv" not in item.parts
                and not item.name.endswith("_helpers.py")
            )
    return sorted(set(files))


def main(argv: list[str]) -> int:
    findings: list[str] = []
    for path in python_files(argv):
        for line, name in unused_imports(path):
            findings.append(f"{path}:{line}: unused import `{name}`")
    if findings:
        print("\n".join(findings), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
