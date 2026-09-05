"""Resource-policy checks shared by the PWA cache operational audit."""

from __future__ import annotations

from pathlib import Path
from typing import Any, get_args

from core.providers.agentic_models import RuntimeDataClass
from scripts.pwa_cache_audit_io import integer_field, object_field, positive_or_zero_integer


INVENTORY_PATH = Path("docs/product/pwa_cache_resource_inventory.v2.json")
RUNTIME_RESOURCE_DECLARATIONS_PATH = Path(
    "apps/base-shell/frontend/src/pwaDataCacheResourceDeclarations.v1.json"
)
RUNTIME_RESOURCE_SCHEMA = "maverick.pwa-data-cache-runtime-resources.v1"
CANONICAL_DATA_CLASSES = frozenset(get_args(RuntimeDataClass))
LOCAL_PERSISTENCE_POLICIES = frozenset({"deny", "session", "cache"})


def audit_resource_inventory(
    inventory: dict[str, Any],
    policy: dict[str, Any],
    errors: list[str],
) -> None:
    budgets = object_field(policy, "runtime_budgets", errors)
    max_entry = integer_field(budgets, "inventory_max_entry_bytes", errors)
    max_scope = integer_field(budgets, "inventory_max_scope_bytes", errors)
    class_rules = _data_class_rules(policy, errors)
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
        fresh_ttl = resource.get("fresh_ttl_seconds")
        expiry_ttl = resource.get("expiry_ttl_seconds")
        if not isinstance(app_ids, list) or not app_ids or not all(_bounded_text(item) for item in app_ids):
            errors.append(f"{label}.app_ids must contain bounded app ids")
            continue
        if not _bounded_text(name):
            errors.append(f"{label}.resource is required")
            continue
        for app_id in app_ids:
            identity = (app_id, name)
            if identity in seen:
                errors.append(f"{label}: duplicate resource {app_id}/{name}")
            seen.add(identity)

        if persistence not in LOCAL_PERSISTENCE_POLICIES:
            errors.append(f"{label}: invalid local persistence policy")
        _audit_data_class_policy(resource, data_class, persistence, class_rules, label, errors)
        for approval in ("cache_approved", "privacy_approved", "regulated_allowlisted"):
            if approval in resource and not isinstance(resource[approval], bool):
                errors.append(f"{label}.{approval} must be a boolean")
        if "runtime_schema_revision" in resource:
            if not _bounded_text(resource["runtime_schema_revision"]):
                errors.append(f"{label}.runtime_schema_revision must be bounded text")
        if "runtime_schema_revision" in resource or "invalidation_aliases" in resource:
            aliases = resource.get("invalidation_aliases")
            if (
                not isinstance(aliases, list)
                or not aliases
                or not all(_bounded_text(alias) for alias in aliases)
                or len(aliases) != len(set(aliases))
            ):
                errors.append(
                    f"{label}.invalidation_aliases must contain unique bounded resource aliases"
                )

        limits = (entry_bytes, scope_bytes, fresh_ttl, expiry_ttl)
        if not all(positive_or_zero_integer(value) for value in limits):
            errors.append(f"{label}: cache TTL and byte limits must be non-negative integers")
            continue
        if persistence == "deny" and any(value != 0 for value in limits):
            errors.append(f"{label}: deny resources must have zero TTL and byte budgets")
        if persistence != "deny" and (entry_bytes <= 0 or scope_bytes < entry_bytes):
            errors.append(f"{label}: persisted resources require a positive bounded scope")
        if expiry_ttl < fresh_ttl:
            errors.append(f"{label}: expiry TTL must not precede fresh TTL")
        if max_entry is not None and entry_bytes > max_entry:
            errors.append(f"{label}: entry budget {entry_bytes} exceeds {max_entry}")
        if max_scope is not None and scope_bytes > max_scope:
            errors.append(f"{label}: scope budget {scope_bytes} exceeds {max_scope}")


def audit_runtime_resource_declarations(
    inventory: dict[str, Any],
    declarations: dict[str, Any],
    errors: list[str],
) -> None:
    if declarations.get("schema") != RUNTIME_RESOURCE_SCHEMA:
        errors.append(
            f"{RUNTIME_RESOURCE_DECLARATIONS_PATH}: expected schema {RUNTIME_RESOURCE_SCHEMA}"
        )
    if declarations.get("policy_revision") != inventory.get("policy_revision"):
        errors.append(f"{RUNTIME_RESOURCE_DECLARATIONS_PATH}: policy revision differs from inventory")
    manifest_classes = declarations.get("canonical_data_classes")
    if (
        not isinstance(manifest_classes, list)
        or not all(isinstance(value, str) for value in manifest_classes)
        or len(manifest_classes) != len(set(manifest_classes))
        or set(manifest_classes) != CANONICAL_DATA_CLASSES
    ):
        errors.append(
            f"{RUNTIME_RESOURCE_DECLARATIONS_PATH}: canonical_data_classes differs from RuntimeDataClass"
        )

    inventory_rows = _inventory_by_identity(inventory, errors)
    runtime_rows = declarations.get("resources")
    if not isinstance(runtime_rows, list) or not runtime_rows:
        errors.append(f"{RUNTIME_RESOURCE_DECLARATIONS_PATH}: resources must be a non-empty array")
        return

    declared: set[tuple[str, str]] = set()
    for index, record in enumerate(runtime_rows):
        label = f"{RUNTIME_RESOURCE_DECLARATIONS_PATH}: resources[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{label} must be an object")
            continue
        app_id = record.get("app_id")
        resource_name = record.get("resource")
        if not _bounded_text(app_id) or not _bounded_text(resource_name):
            errors.append(f"{label}: app_id and resource must be bounded text")
            continue
        identity = (app_id, resource_name)
        if identity in declared:
            errors.append(f"{label}: duplicate runtime resource {app_id}/{resource_name}")
            continue
        declared.add(identity)
        inventory_row = inventory_rows.get(identity)
        if inventory_row is None:
            errors.append(f"{label}: {app_id}/{resource_name} is absent from the inventory")
            continue
        _compare_runtime_record(record, inventory_row, label, errors)

    expected = {
        identity
        for identity, resource in inventory_rows.items()
        if "runtime_schema_revision" in resource
    }
    if declared != expected:
        errors.append(
            "runtime resource inventory mismatch: "
            f"declarations={sorted(declared)}, inventory={sorted(expected)}"
        )


def _data_class_rules(
    policy: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    rules = object_field(policy, "data_class_persistence", errors)
    keys = set(rules)
    if keys != CANONICAL_DATA_CLASSES:
        errors.append(
            "data_class_persistence must enumerate the complete canonical class set: "
            f"policy={sorted(keys)}, runtime={sorted(CANONICAL_DATA_CLASSES)}"
        )
    return rules


def _audit_data_class_policy(
    resource: dict[str, Any],
    data_class: object,
    persistence: object,
    class_rules: dict[str, Any],
    label: str,
    errors: list[str],
) -> None:
    if data_class not in CANONICAL_DATA_CLASSES:
        errors.append(f"{label}: unknown canonical data class {data_class!r}")
        return
    rule = class_rules.get(data_class)
    if not isinstance(rule, dict):
        errors.append(f"{label}: no persistence rule for {data_class}")
        return
    allowed = rule.get("allowed")
    requirements = rule.get("cache_requires")
    if not isinstance(allowed, list) or not set(allowed) <= LOCAL_PERSISTENCE_POLICIES:
        errors.append(f"data_class_persistence.{data_class}.allowed is invalid")
    elif persistence not in allowed:
        errors.append(f"{label}: {data_class} cannot use {persistence} persistence")
    if not isinstance(requirements, list) or not all(
        requirement in {"cache_approved", "privacy_approved", "regulated_allowlisted"}
        for requirement in requirements
    ):
        errors.append(f"data_class_persistence.{data_class}.cache_requires is invalid")
    elif persistence == "cache":
        for requirement in requirements:
            if resource.get(requirement) is not True:
                errors.append(f"{label}: {data_class} cache requires {requirement}=true")


def _inventory_by_identity(
    inventory: dict[str, Any],
    errors: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    resources = inventory.get("resources")
    if not isinstance(resources, list):
        errors.append(f"{INVENTORY_PATH}: resources must be an array")
        return result
    for record in resources:
        if not isinstance(record, dict) or not isinstance(record.get("app_ids"), list):
            continue
        resource_name = record.get("resource")
        if not isinstance(resource_name, str):
            continue
        for app_id in record["app_ids"]:
            if isinstance(app_id, str):
                result[(app_id, resource_name)] = record
    return result


def _compare_runtime_record(
    runtime: dict[str, Any],
    inventory: dict[str, Any],
    label: str,
    errors: list[str],
) -> None:
    direct_fields = (
        "canonical_data_class",
        "provenance",
        "local_persistence_policy",
        "max_entry_bytes",
        "max_scope_bytes",
    )
    for field in direct_fields:
        if runtime.get(field) != inventory.get(field):
            errors.append(f"{label}.{field} differs from inventory")
    conversions = (
        ("fresh_ttl_ms", "fresh_ttl_seconds"),
        ("expiry_ttl_ms", "expiry_ttl_seconds"),
    )
    for runtime_field, inventory_field in conversions:
        inventory_value = inventory.get(inventory_field)
        expected = inventory_value * 1_000 if positive_or_zero_integer(inventory_value) else None
        if runtime.get(runtime_field) != expected:
            errors.append(f"{label}.{runtime_field} differs from inventory {inventory_field}")
    for approval in ("cache_approved", "privacy_approved", "regulated_allowlisted"):
        if runtime.get(approval) is not bool(inventory.get(approval, False)):
            errors.append(f"{label}.{approval} differs from inventory")
    if runtime.get("schema_revision") != inventory.get("runtime_schema_revision"):
        errors.append(f"{label}.schema_revision differs from inventory runtime_schema_revision")
    aliases = runtime.get("aliases")
    if (
        not isinstance(aliases, list)
        or not aliases
        or not all(_bounded_text(alias) for alias in aliases)
        or len(aliases) != len(set(aliases))
    ):
        errors.append(f"{label}.aliases must contain bounded resource aliases")
    elif aliases != inventory.get("invalidation_aliases"):
        errors.append(f"{label}.aliases differs from inventory invalidation_aliases")


def _bounded_text(value: object) -> bool:
    return isinstance(value, str) and value == value.strip() and 0 < len(value) <= 128
