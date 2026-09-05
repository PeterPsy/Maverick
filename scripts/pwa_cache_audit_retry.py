"""SDK-owned executor and runtime-registry checks for mutation retries."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

from scripts.pwa_cache_audit_io import read_text


MUTATION_RETRY_REGISTRY_PATH = Path("packages/pwa-cache/src/mutationRetryRegistry.v2.json")
MUTATION_RETRY_REGISTRY_SCHEMA = "maverick.pwa-mutation-retry-registry.v2"
AUDIT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{4,126}\.v[1-9][0-9]*$")
ACTION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,127}$")
ENDPOINT_PATTERN = re.compile(r"^/api/[A-Za-z0-9._~!$&'()*+,;=:@%/-]{1,506}$")
MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
FACTORY_CALL = re.compile(r"\bcreateMutationRetryExecutor\s*\(")
MUTATION_RUN_CALL = re.compile(r"\.runMutation\s*\(")
LEGACY_RETRY_RUN_CALL = re.compile(r"\.run\s*\(")
LEGACY_MUTATION_CONTRACT = re.compile(r"\bcreateMutationRetryContract\s*\(")
RAW_DEDUPLICATION_CONTRACT = re.compile(r"\bserverDeduplicates\b")
FACTORY_IMPLEMENTATION = Path("packages/pwa-cache/src/mutationRetry.ts")
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

MutationTarget = tuple[str, str, str]


def audit_mutation_retry_registry(
    registry: dict[str, Any],
    approved: dict[str, MutationTarget],
    errors: list[str],
) -> None:
    if registry.get("schema") != MUTATION_RETRY_REGISTRY_SCHEMA:
        errors.append(
            f"{MUTATION_RETRY_REGISTRY_PATH}: expected schema {MUTATION_RETRY_REGISTRY_SCHEMA}"
        )
    values = registry.get("contracts")
    if not isinstance(values, list):
        errors.append(f"{MUTATION_RETRY_REGISTRY_PATH}: contracts must be an array")
        return
    runtime: dict[str, MutationTarget] = {}
    expected_fields = {"audit_id", "method", "endpoint", "action"}
    for index, value in enumerate(values):
        label = f"{MUTATION_RETRY_REGISTRY_PATH}: contracts[{index}]"
        if not isinstance(value, dict) or set(value) != expected_fields:
            errors.append(f"{label} must contain exactly audit_id, method, endpoint, and action")
            continue
        audit_id = value.get("audit_id")
        target = mutation_target(value)
        if (
            not isinstance(audit_id, str)
            or not AUDIT_ID_PATTERN.fullmatch(audit_id)
            or audit_id in runtime
            or target is None
        ):
            errors.append(f"{label} is invalid or duplicated")
            continue
        runtime[audit_id] = target
    if runtime != approved:
        errors.append(
            "retry audit registry target mismatch: "
            f"runtime={sorted(runtime.items())}, policy={sorted(approved.items())}"
        )


def production_retry_audit_ids(
    root: Path,
    errors: list[str],
    approved: dict[str, MutationTarget] | None = None,
) -> set[str]:
    """Discover direct SDK-executor uses across every production source tree.

    RetryCoordinator.runMutation() has no caller operation callback and accepts
    only a factory-issued executor whose request is performed by the SDK. This
    scan also bans legacy/raw contracts and requires literal registry metadata
    for CI evidence/parity checks. Computed values cannot escape discovery.
    """
    discovered: set[str] = set()
    owners: dict[str, Path] = {}
    for path in production_source_paths(root):
        relative = path.relative_to(root)
        source = read_text(path, errors)
        if relative == FACTORY_IMPLEMENTATION:
            continue
        if LEGACY_MUTATION_CONTRACT.search(source):
            errors.append(
                f"{relative}: legacy mutation retry contracts are forbidden; "
                "use createMutationRetryExecutor()"
            )
        if RAW_DEDUPLICATION_CONTRACT.search(source):
            errors.append(
                f"{relative}: raw mutation retry contracts are forbidden; "
                "use the createMutationRetryExecutor() SDK transport factory"
            )
        audit_legacy_retry_run_calls(relative, source, errors)
        audit_mutation_run_calls(relative, source, errors)
        starts = [match.end() - 1 for match in FACTORY_CALL.finditer(source)]
        for open_parenthesis in starts:
            body = balanced_call_body(source, open_parenthesis)
            if body is None:
                errors.append(f"{relative}: malformed createMutationRetryExecutor() call")
                continue
            audit_id = literal_property(body, "auditId")
            method = literal_property(body, "method")
            endpoint = literal_property(body, "endpoint")
            action = literal_property(body, "action")
            if audit_id is None:
                errors.append(
                    f"{relative}: createMutationRetryExecutor() requires one literal auditId"
                )
                continue
            if None in (method, endpoint, action):
                errors.append(
                    f"{relative}: retry factory {audit_id} requires literal method, endpoint, and action"
                )
                continue
            target = mutation_target({"method": method, "endpoint": endpoint, "action": action})
            if target is None:
                errors.append(f"{relative}: retry factory {audit_id} has an invalid mutation target")
                continue
            owner = owners.get(audit_id)
            if owner is not None:
                errors.append(
                    f"{relative}: retry auditId {audit_id} is duplicated in {owner.relative_to(root)}"
                )
            else:
                owners[audit_id] = path
            if approved is not None and approved.get(audit_id) != target:
                errors.append(
                    f"{relative}: retry factory {audit_id} target differs from the operational policy"
                )
            discovered.add(audit_id)
    return discovered


def audit_mutation_run_calls(relative: Path, source: str, errors: list[str]) -> None:
    for match in MUTATION_RUN_CALL.finditer(source):
        body = balanced_call_body(source, match.end() - 1)
        if body is None:
            errors.append(f"{relative}: malformed runMutation() call")
            continue
        if literal_or_method_property(body, "operation") or literal_or_method_property(body, "classify"):
            errors.append(
                f"{relative}: runMutation() cannot accept an operation/classifier callback; "
                "the SDK-owned executor must issue the request"
            )


def audit_legacy_retry_run_calls(relative: Path, source: str, errors: list[str]) -> None:
    for match in LEGACY_RETRY_RUN_CALL.finditer(source):
        body = balanced_call_body(source, match.end() - 1)
        if body is None:
            continue
        request_fields = ("action", "endpoint", "method", "mutation")
        if literal_or_method_property(body, "operation") and any(
            literal_or_method_property(body, field) for field in request_fields
        ):
            errors.append(
                f"{relative}: legacy callback retry API is forbidden; use runOpaque(), "
                "runRequest(), or runMutation()"
            )


def mutation_target(record: dict[str, Any]) -> MutationTarget | None:
    method = record.get("method")
    endpoint = record.get("endpoint")
    action = record.get("action")
    if (
        not isinstance(method, str)
        or method not in MUTATION_METHODS
        or not isinstance(endpoint, str)
        or not ENDPOINT_PATTERN.fullmatch(endpoint)
        or not isinstance(action, str)
        or not ACTION_PATTERN.fullmatch(action)
    ):
        return None
    return method, endpoint, action


def production_source_paths(root: Path) -> list[Path]:
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
    return sorted(source_paths)


def literal_property(call_body: str, property_name: str) -> str | None:
    pattern = re.compile(
        rf"\b{re.escape(property_name)}\s*:\s*(?P<quote>['\"])(?P<value>[^'\"\\\r\n]+)(?P=quote)"
    )
    structure = code_structure(call_body)
    matches = [
        match.group("value")
        for match in pattern.finditer(call_body)
        if structure[match.start()] == (True, 1, 0, 0)
    ]
    return matches[0] if len(matches) == 1 else None


def literal_or_method_property(call_body: str, property_name: str) -> bool:
    structure = code_structure(call_body)
    return any(
        structure[match.start()] == (True, 1, 0, 0)
        for match in re.finditer(rf"\b{re.escape(property_name)}\s*(?::|\()", call_body)
    )


def code_structure(source: str) -> list[tuple[bool, int, int, int]]:
    """Record whether each offset is top-level code in one call argument object."""
    structure: list[tuple[bool, int, int, int]] = []
    braces = parentheses = brackets = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = 0
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        in_code = quote is None and not line_comment and not block_comment
        structure.append((in_code, braces, parentheses, brackets))
        if line_comment:
            if char in "\r\n":
                line_comment = False
        elif block_comment:
            if char == "*" and following == "/":
                block_comment = False
        elif quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char == "/" and following == "/":
            line_comment = True
        elif char == "/" and following == "*":
            block_comment = True
        elif char in "'\"`":
            quote = char
        elif char == "{":
            braces += 1
        elif char == "}":
            braces = max(0, braces - 1)
        elif char == "(":
            parentheses += 1
        elif char == ")":
            parentheses = max(0, parentheses - 1)
        elif char == "[":
            brackets += 1
        elif char == "]":
            brackets = max(0, brackets - 1)
        index += 1
    return structure


def balanced_call_body(source: str, open_parenthesis: int) -> str | None:
    """Return one call body while ignoring delimiters in strings and comments."""
    depth = 0
    index = open_parenthesis
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
        elif block_comment:
            if char == "*" and following == "/":
                block_comment = False
                index += 1
        elif quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char == "/" and following == "/":
            line_comment = True
            index += 1
        elif char == "/" and following == "*":
            block_comment = True
            index += 1
        elif char in "'\"`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[open_parenthesis + 1:index]
        index += 1
    return None
