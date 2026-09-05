"""Production-source and runtime-registry checks for mutation retries."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

from scripts.pwa_cache_audit_io import read_text


MUTATION_RETRY_REGISTRY_PATH = Path("packages/pwa-cache/src/mutationRetryRegistry.v1.json")
MUTATION_RETRY_REGISTRY_SCHEMA = "maverick.pwa-mutation-retry-registry.v1"
AUDIT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{4,126}\.v[1-9][0-9]*$")
PRODUCTION_AUDIT_LITERAL = re.compile(r"\bauditId\s*:\s*[\"']([^\"']+)[\"']")
PRODUCTION_MUTATION_CONTRACT = re.compile(
    r"\bserverDeduplicates\s*:\s*true\s*(?=,|\})"
)
PRODUCTION_SOURCE_SUFFIXES = frozenset({
    ".cjs",
    ".cts",
    ".js",
    ".jsx",
    ".mjs",
    ".mts",
    ".svelte",
    ".ts",
    ".tsx",
    ".vue",
})
PRODUCTION_SOURCE_ROOTS = ("apps", "core", "packages", "scripts")
EXCLUDED_SOURCE_PARTS = frozenset({
    ".git",
    ".maverick",
    ".next",
    ".venv",
    "__tests__",
    "artifacts",
    "build",
    "coverage",
    "dist",
    "fixtures",
    "node_modules",
    "out",
    "test",
    "tests",
    "vendor",
    "workspaces",
})


def audit_mutation_retry_registry(
    registry: dict[str, Any],
    approved: set[str],
    errors: list[str],
) -> None:
    if registry.get("schema") != MUTATION_RETRY_REGISTRY_SCHEMA:
        errors.append(
            f"{MUTATION_RETRY_REGISTRY_PATH}: expected schema {MUTATION_RETRY_REGISTRY_SCHEMA}"
        )
    values = registry.get("audit_ids")
    if not isinstance(values, list):
        errors.append(f"{MUTATION_RETRY_REGISTRY_PATH}: audit_ids must be an array")
        return
    runtime_ids: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, str) or not AUDIT_ID_PATTERN.fullmatch(value) or value in runtime_ids:
            errors.append(f"{MUTATION_RETRY_REGISTRY_PATH}: audit_ids[{index}] is invalid or duplicated")
            continue
        runtime_ids.add(value)
    if runtime_ids != approved:
        errors.append(
            f"retry audit registry mismatch: runtime={sorted(runtime_ids)}, policy={sorted(approved)}"
        )


def production_retry_audit_ids(root: Path, errors: list[str]) -> set[str]:
    """Find retryable mutation object literals in every production browser source tree."""
    discovered: set[str] = set()
    owners: dict[str, Path] = {}
    source_paths: list[Path] = []
    for source_root_name in PRODUCTION_SOURCE_ROOTS:
        source_root = root / source_root_name
        if not source_root.is_dir():
            continue
        for directory, names, files in os.walk(source_root):
            names[:] = sorted(name for name in names if name not in EXCLUDED_SOURCE_PARTS)
            source_paths.extend(
                Path(directory) / name
                for name in files
                if Path(name).suffix.lower() in PRODUCTION_SOURCE_SUFFIXES
            )
    for path in sorted(source_paths):
        relative = path.relative_to(root)
        source = read_text(path, errors)
        audit_ids = PRODUCTION_AUDIT_LITERAL.findall(source)
        mutation_contracts = len(PRODUCTION_MUTATION_CONTRACT.findall(source))
        if mutation_contracts != len(audit_ids):
            errors.append(
                f"{relative}: every retryable mutation contract requires one literal auditId"
            )
        for audit_id in audit_ids:
            owner = owners.get(audit_id)
            if owner is not None:
                errors.append(
                    f"{relative}: retry auditId {audit_id} is duplicated in {owner.relative_to(root)}"
                )
            else:
                owners[audit_id] = path
            discovered.add(audit_id)
    return discovered
