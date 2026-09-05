#!/usr/bin/env python3
"""Audit PWA cache budgets, resource policy, and mutation retry approvals."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from core.apps.frontend_assets import FrontendAssetManifestError, load_frontend_asset_manifest
from core.pwa.rollout import ROLLOUT_USER_PERCENT_SUFFIX, ROLLOUT_WORKSPACE_PERCENT_SUFFIX
from scripts.pwa_cache_audit_io import (
    integer_field,
    load_json,
    object_field,
    positive_integer,
    positive_or_zero_integer,
    read_text,
    typescript_integer_constant,
)


POLICY_PATH = Path("docs/product/pwa_cache_operational_policy.v1.json")
INVENTORY_PATH = Path("docs/product/pwa_cache_resource_inventory.v2.json")
POLICY_SCHEMA = "maverick.pwa-cache-operational-policy.v1"
INVENTORY_SCHEMA = "maverick.pwa-cache-resource-inventory.v2"
AUDIT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{4,126}\.v[1-9][0-9]*$")
PRODUCTION_AUDIT_LITERAL = re.compile(r"\bauditId\s*:\s*[\"']([^\"']+)[\"']")


def audit_repository(root: Path) -> list[str]:
    """Return every violation rather than hiding later failures behind the first."""
    errors: list[str] = []
    policy = load_json(root / POLICY_PATH, errors)
    inventory = load_json(root / INVENTORY_PATH, errors)
    if not isinstance(policy, dict) or not isinstance(inventory, dict):
        return errors
    if policy.get("schema") != POLICY_SCHEMA:
        errors.append(f"{POLICY_PATH}: expected schema {POLICY_SCHEMA}")
    if inventory.get("schema") != INVENTORY_SCHEMA:
        errors.append(f"{INVENTORY_PATH}: expected schema {INVENTORY_SCHEMA}")
    audit_runtime_budgets(root, policy, errors)
    audit_frontend_manifests(root, policy, errors)
    audit_resource_inventory(inventory, policy, errors)
    audit_retry_policy(root, policy, errors)
    audit_rollout_contract(policy, errors)
    return errors


def audit_frontend_manifests(root: Path, policy: dict[str, Any], errors: list[str]) -> None:
    budgets = object_field(policy, "asset_budgets", errors)
    max_asset = integer_field(budgets, "max_frontend_asset_bytes", errors)
    max_manifest = integer_field(budgets, "max_frontend_manifest_bytes", errors)
    max_precache = integer_field(budgets, "max_shell_precache_bytes", errors)
    builds = sorted(path for path in (root / "apps").glob("*/frontend/dist") if path.is_dir())
    if not builds:
        errors.append("no frontend builds were found")
        return
    manifest_count = 0
    for build in builds:
        output_files = [
            path for path in build.rglob("*")
            if path.is_file() and path.name != "maverick-frontend-assets.json" and path.suffix != ".map"
        ]
        relative_build = build.relative_to(root)
        total = sum(path.stat().st_size for path in output_files)
        largest = max((path.stat().st_size for path in output_files), default=0)
        if max_asset is not None and largest > max_asset:
            errors.append(f"{relative_build}: asset size {largest} exceeds {max_asset}")
        if max_manifest is not None and total > max_manifest:
            errors.append(f"{relative_build}: frontend bytes {total} exceed {max_manifest}")

        manifest_path = build / "maverick-frontend-assets.json"
        if not manifest_path.is_file():
            continue
        manifest_count += 1
        relative_manifest = manifest_path.relative_to(root)
        try:
            manifest = load_frontend_asset_manifest(build, required=True, verify_files=True)
        except (FrontendAssetManifestError, OSError) as error:
            errors.append(f"{relative_manifest}: {error}")
            continue
        assert manifest is not None
        declared = {record.path for record in (*manifest.immutable, *manifest.revalidated)}
        actual = {path.relative_to(build).as_posix() for path in output_files}
        undeclared = sorted(actual - declared)
        if undeclared:
            errors.append(f"{relative_manifest}: undeclared build outputs: {', '.join(undeclared)}")
        if manifest_path.parts[-4] == "base-shell" and max_precache is not None:
            precache_bytes = sum(record.size_bytes for record in manifest.precache)
            if precache_bytes > max_precache:
                errors.append(f"{relative_manifest}: shell precache {precache_bytes} exceeds {max_precache}")
    if manifest_count == 0:
        errors.append("no committed frontend asset manifests were found")


def audit_runtime_budgets(root: Path, policy: dict[str, Any], errors: list[str]) -> None:
    budgets = object_field(policy, "runtime_budgets", errors)
    expected = {
        "DEFAULT_PWA_CACHE_APP_BUDGET_BYTES": ("packages/pwa-cache/src/client.ts", "structured_app_bytes"),
        "DEFAULT_PWA_CACHE_GLOBAL_BUDGET_BYTES": ("packages/pwa-cache/src/client.ts", "structured_global_bytes"),
        "DEFAULT_PWA_FILE_CACHE_MAX_ENTRY_BYTES": ("packages/pwa-cache/src/fileCacheTypes.ts", "file_entry_bytes"),
        "DEFAULT_PWA_FILE_CACHE_SCOPE_BUDGET_BYTES": (
            "packages/pwa-cache/src/fileCacheTypes.ts",
            "file_scope_bytes",
        ),
        "DEFAULT_PWA_FILE_CACHE_GLOBAL_BUDGET_BYTES": ("packages/pwa-cache/src/fileCacheTypes.ts", "file_global_bytes"),
    }
    for constant, (source_path, budget_name) in expected.items():
        expected_value = integer_field(budgets, budget_name, errors)
        actual_value = typescript_integer_constant(root / source_path, constant)
        if actual_value is None:
            errors.append(f"{source_path}: unable to resolve {constant}")
        elif expected_value is not None and actual_value != expected_value:
            errors.append(f"{source_path}: {constant}={actual_value}, policy requires {expected_value}")


def audit_resource_inventory(inventory: dict[str, Any], policy: dict[str, Any], errors: list[str]) -> None:
    budgets = object_field(policy, "runtime_budgets", errors)
    max_entry = integer_field(budgets, "inventory_max_entry_bytes", errors)
    max_scope = integer_field(budgets, "inventory_max_scope_bytes", errors)
    resources = inventory.get("resources")
    if not isinstance(resources, list) or not resources:
        errors.append(f"{INVENTORY_PATH}: resources must be a non-empty array")
        return
    seen: set[tuple[str, str]] = set()
    for index, resource in enumerate(resources):
        label = f"{INVENTORY_PATH}: resources[{index}]"
        if not isinstance(resource, dict):
            errors.append(f"{label} must be an object")
            continue
        app_ids = resource.get("app_ids")
        name = resource.get("resource")
        persistence = resource.get("local_persistence_policy")
        data_class = resource.get("canonical_data_class")
        entry_bytes = resource.get("max_entry_bytes")
        scope_bytes = resource.get("max_scope_bytes")
        if not isinstance(app_ids, list) or not app_ids or not all(isinstance(item, str) and item for item in app_ids):
            errors.append(f"{label}.app_ids must contain bounded app ids")
            continue
        if not isinstance(name, str) or not name:
            errors.append(f"{label}.resource is required")
            continue
        for app_id in app_ids:
            identity = (app_id, name)
            if identity in seen:
                errors.append(f"{label}: duplicate resource {app_id}/{name}")
            seen.add(identity)
        if persistence not in {"deny", "session", "cache"}:
            errors.append(f"{label}: invalid local persistence policy")
        if not positive_or_zero_integer(entry_bytes) or not positive_or_zero_integer(scope_bytes):
            errors.append(f"{label}: cache byte limits must be non-negative integers")
            continue
        if persistence == "deny" and (entry_bytes != 0 or scope_bytes != 0):
            errors.append(f"{label}: deny resources must have zero byte budgets")
        if persistence != "deny" and (entry_bytes <= 0 or scope_bytes < entry_bytes):
            errors.append(f"{label}: persisted resources require a positive bounded scope")
        if data_class in {"credential_or_secret", "unclassified"} and persistence != "deny":
            errors.append(f"{label}: {data_class} must fail closed to deny")
        if max_entry is not None and entry_bytes > max_entry:
            errors.append(f"{label}: entry budget {entry_bytes} exceeds {max_entry}")
        if max_scope is not None and scope_bytes > max_scope:
            errors.append(f"{label}: scope budget {scope_bytes} exceeds {max_scope}")


def audit_retry_policy(root: Path, policy: dict[str, Any], errors: list[str]) -> None:
    retry = object_field(policy, "retry_policy", errors)
    safe_methods = retry.get("safe_methods")
    statuses = retry.get("retryable_http_statuses")
    attempts = retry.get("max_mutation_attempts")
    source_path = root / "packages/pwa-cache/src/retryPolicy.ts"
    retry_source = read_text(source_path, errors)
    retry_runtime = read_text(root / "packages/pwa-cache/src/retry.ts", errors)
    if isinstance(safe_methods, list):
        literal = "new Set([" + ", ".join(json.dumps(item) for item in safe_methods) + "])"
        if literal not in retry_source:
            errors.append("retryPolicy.ts safe methods differ from operational policy")
    else:
        errors.append("retry_policy.safe_methods must be an array")
    if isinstance(statuses, list):
        literal = "new Set([" + ", ".join(str(item) for item in statuses) + "])"
        if literal not in retry_source:
            errors.append("retryPolicy.ts retryable statuses differ from operational policy")
    else:
        errors.append("retry_policy.retryable_http_statuses must be an array")
    if not positive_integer(attempts) or f"positive(options.maxMutationAttempts, {attempts})" not in retry_runtime:
        errors.append("retry runtime mutation attempt cap differs from operational policy")
    if "auditId: string;" not in retry_source or "RETRY_AUDIT_ID_PATTERN.test(contract.auditId)" not in retry_source:
        errors.append("mutation retry runtime does not require a validated audit id")

    contracts = retry.get("mutation_contracts")
    if not isinstance(contracts, list):
        errors.append("retry_policy.mutation_contracts must be an array")
        return
    approved: set[str] = set()
    for index, contract in enumerate(contracts):
        label = f"retry_policy.mutation_contracts[{index}]"
        if not isinstance(contract, dict):
            errors.append(f"{label} must be an object")
            continue
        audit_id = contract.get("audit_id")
        if not isinstance(audit_id, str) or not AUDIT_ID_PATTERN.fullmatch(audit_id) or audit_id in approved:
            errors.append(f"{label}.audit_id is invalid or duplicated")
            continue
        approved.add(audit_id)
        audit_retry_contract_sources(root, contract, label, errors)
    discovered = production_retry_audit_ids(root, errors)
    if discovered != approved:
        errors.append(f"retry audit registry mismatch: source={sorted(discovered)}, policy={sorted(approved)}")


def audit_retry_contract_sources(root: Path, contract: dict[str, Any], label: str, errors: list[str]) -> None:
    audit_id = str(contract.get("audit_id") or "")
    action = str(contract.get("action") or "")
    endpoint = str(contract.get("endpoint") or "")
    client_path = contract.get("client_source")
    server_paths = contract.get("server_sources")
    test_path = contract.get("test_source")
    if contract.get("method") not in {"POST", "PUT", "PATCH", "DELETE"}:
        errors.append(f"{label}.method must be a mutation method")
    if not isinstance(client_path, str) or not isinstance(server_paths, list) or not isinstance(test_path, str):
        errors.append(f"{label}: client/server/test evidence paths are required")
        return
    client = read_text(root / client_path, errors)
    for needle in (audit_id, action, endpoint, "idempotencyHeaders", "requestFingerprint"):
        if needle not in client:
            errors.append(f"{client_path}: missing audited retry evidence `{needle}`")
    server = "\n".join(read_text(root / str(path), errors) for path in server_paths)
    for needle in (action, "idempotency_key", "request_fingerprint", "already bound"):
        if needle not in server:
            errors.append(f"{label}: server deduplication evidence `{needle}` is missing")
    test = read_text(root / test_path, errors)
    for needle in (action, "idempotency_key", "request_fingerprint", "replay"):
        if needle not in test:
            errors.append(f"{test_path}: retry regression evidence `{needle}` is missing")


def production_retry_audit_ids(root: Path, errors: list[str]) -> set[str]:
    discovered: set[str] = set()
    for extension in ("*.ts", "*.tsx"):
        for path in (root / "apps").glob(f"*/frontend/src/**/{extension}"):
            source = read_text(path, errors)
            audit_ids = PRODUCTION_AUDIT_LITERAL.findall(source)
            mutation_contracts = len(re.findall(r"\bserverDeduplicates\s*:\s*true\b", source))
            if mutation_contracts != len(audit_ids):
                errors.append(
                    f"{path.relative_to(root)}: every retryable mutation contract requires one literal auditId"
                )
            discovered.update(audit_ids)
    return discovered


def audit_rollout_contract(policy: dict[str, Any], errors: list[str]) -> None:
    rollout = object_field(policy, "rollout", errors)
    if rollout.get("user_percent_suffix") != ROLLOUT_USER_PERCENT_SUFFIX:
        errors.append("rollout user percentage suffix differs from runtime")
    if rollout.get("workspace_percent_suffix") != ROLLOUT_WORKSPACE_PERCENT_SUFFIX:
        errors.append("rollout workspace percentage suffix differs from runtime")


def main() -> int:
    errors = audit_repository(REPOSITORY_ROOT)
    if errors:
        for error in errors:
            print(f"PWA cache audit: {error}", file=sys.stderr)
        return 1
    print("PWA cache operational audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
