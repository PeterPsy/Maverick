"""Shared Core Secrets grant-target discovery and scope policy."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlsplit

from core.api.platform_state import PlatformState
from core.apps.errors import AppHostingError
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.apps.surface_descriptors import app_cli_command_secret_selectors, app_mcp_tool_secret_selectors
from core.secrets.app_delivery import APP_SECRET_ACTION as APP_BACKEND_ACTION, app_secret_target
from core.secrets.errors import SecretError, SecretPolicyError
from core.secrets.target_policy import normalize_target_patterns_or_wildcard, target_allowed


logger = logging.getLogger(__name__)

SecretConsumer = dict[str, object]
SecretConsumersByLogicalName = dict[str, SecretConsumer]


def secret_grant_target_items(
    state: PlatformState,
    *,
    workspace_id: str,
    start_path: Path,
) -> list[dict[str, object]]:
    """Return redaction-safe grant-target metadata for enabled workspace apps."""
    items: list[dict[str, object]] = []
    for binding in enabled_workspace_app_bindings(state.app_store, workspace_id=workspace_id):
        try:
            source_root, parsed = resolve_workspace_app_surface(state.app_store, binding=binding, start_path=start_path)
        except AppHostingError:
            continue
        except Exception:
            logger.exception(
                "Skipping enabled app `%s` in workspace `%s` while listing secret grant targets.",
                binding.app_id,
                workspace_id,
            )
            continue
        declared_logical_names = _declared_secret_logical_names(parsed.contract.permissions.secrets.read)
        app_managed_logical_names = set(_declared_secret_logical_names(parsed.contract.permissions.secrets.write))
        consumers = app_secret_consumers_by_logical_name(
            source_root=source_root,
            declared_logical_names=declared_logical_names,
            backend_declared=parsed.contract.entrypoints.backend is not None,
            cli_commands=[str(item).strip() for item in parsed.contract.capabilities.cli_commands if str(item).strip()],
            mcp_tools=[str(item).strip() for item in parsed.contract.capabilities.mcp_tools if str(item).strip()],
        )
        for logical_name in app_managed_logical_names:
            if logical_name in consumers:
                consumers[logical_name]["app_managed"] = True
        logical_names = sorted(
            logical_name for logical_name, consumer in consumers.items() if consumer_requires_secret(consumer)
        )
        if not logical_names:
            continue
        consumer_cli_commands = sorted(
            {command for logical_name in logical_names for command in consumers[logical_name]["cli_commands"]}
        )
        consumer_mcp_tools = sorted(
            {tool for logical_name in logical_names for tool in consumers[logical_name]["mcp_tools"]}
        )
        items.append(
            {
                "app_id": binding.app_id,
                "public_app_id": binding.public_app_id or parsed.app_id,
                "mount_app_id": binding.mount_app_id or binding.app_id,
                "name": parsed.name,
                "status": binding.status,
                "logical_names": logical_names,
                "consumers": {logical_name: consumers[logical_name] for logical_name in logical_names},
                "surfaces": {
                    "backend": any(consumers[logical_name]["backend"] for logical_name in logical_names),
                    "cli_commands": consumer_cli_commands,
                    "mcp_tools": consumer_mcp_tools,
                },
            }
        )
    return items


def enabled_app_secret_consumers(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
) -> SecretConsumersByLogicalName:
    """Resolve one enabled app and return its secret consumer policy metadata."""
    binding = state.app_store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
    if binding.status != "enabled":
        raise SecretPolicyError(f"Workspace app `{app_id}` is not enabled in workspace `{workspace_id}`.")
    try:
        source_root, parsed = resolve_workspace_app_surface(state.app_store, binding=binding, start_path=state.repository_root)
    except AppHostingError as exc:
        raise SecretPolicyError(f"Workspace app `{app_id}` is enabled but its surface is unavailable.") from exc
    return app_secret_consumers_by_logical_name(
        source_root=source_root,
        declared_logical_names=_declared_secret_logical_names(parsed.contract.permissions.secrets.read),
        backend_declared=parsed.contract.entrypoints.backend is not None,
        cli_commands=[str(item).strip() for item in parsed.contract.capabilities.cli_commands if str(item).strip()],
        mcp_tools=[str(item).strip() for item in parsed.contract.capabilities.mcp_tools if str(item).strip()],
    )


def app_secret_consumers_by_logical_name(
    *,
    source_root: Path,
    declared_logical_names: list[str],
    backend_declared: bool,
    cli_commands: list[str],
    mcp_tools: list[str],
) -> SecretConsumersByLogicalName:
    """Build logical-name consumer metadata from app contract and descriptors."""
    consumers: SecretConsumersByLogicalName = {
        logical_name: {
            "backend": backend_declared,
            "cli_commands": [],
            "mcp_tools": [],
            "resource_scoped": False,
            "resource_types": [],
        }
        for logical_name in declared_logical_names
    }
    for command in cli_commands:
        for selector in app_cli_command_secret_selectors(
            source_root,
            command,
            declared_secret_names=declared_logical_names,
        ):
            for logical_name in selector.logical_names:
                consumer = _consumer_record(consumers, logical_name)
                cli_consumers = consumer["cli_commands"]
                if isinstance(cli_consumers, list) and command not in cli_consumers:
                    cli_consumers.append(command)
                _record_consumer_resource_scope(consumer, selector.resource_type)
    for tool in mcp_tools:
        for selector in app_mcp_tool_secret_selectors(
            source_root,
            tool,
            declared_secret_names=declared_logical_names,
        ):
            for logical_name in selector.logical_names:
                consumer = _consumer_record(consumers, logical_name)
                mcp_consumers = consumer["mcp_tools"]
                if isinstance(mcp_consumers, list) and tool not in mcp_consumers:
                    mcp_consumers.append(tool)
                _record_consumer_resource_scope(consumer, selector.resource_type)
    return consumers


def assert_app_backend_resource_scope_allowed(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    actions: list[str],
    resource_type: str | None,
    resource_id: str | None,
) -> None:
    """Require app.backend grants to match the app-declared resource scope mode."""
    normalized_actions = {str(action).strip().lower() for action in actions}
    if APP_BACKEND_ACTION not in normalized_actions:
        return
    assert_consumer_resource_scope_allowed(
        app_id=app_id,
        logical_name=logical_name,
        actions=actions,
        resource_type=resource_type,
        resource_id=resource_id,
        consumers=enabled_app_secret_consumers(state, workspace_id=workspace_id, app_id=app_id),
    )


def assert_consumer_resource_scope_allowed(
    *,
    app_id: str,
    logical_name: str,
    actions: list[str],
    resource_type: str | None,
    resource_id: str | None,
    consumers: SecretConsumersByLogicalName,
) -> None:
    """Require a grant or app write to follow consumer-declared resource scope."""
    normalized_actions = {str(action).strip().lower() for action in actions}
    if APP_BACKEND_ACTION not in normalized_actions:
        return
    normalized_logical_name = str(logical_name or "").strip().lower()
    normalized_resource_type = _normalize_optional_resource(resource_type)
    normalized_resource_id = _normalize_optional_resource(resource_id)
    if bool(normalized_resource_type) != bool(normalized_resource_id):
        raise SecretPolicyError("App backend secret grants must include both resource_type and resource_id, or neither.")
    consumer = consumers.get(normalized_logical_name)
    if not consumer or not consumer_requires_secret(consumer):
        raise SecretPolicyError(f"App `{app_id}` has no declared consumers for secret logical name `{normalized_logical_name}`.")
    resource_types = _consumer_resource_types(consumer)
    if bool(consumer.get("resource_scoped")):
        if not normalized_resource_type or not normalized_resource_id:
            raise SecretPolicyError(
                f"Secret logical name `{normalized_logical_name}` for app `{app_id}` requires resource_type and resource_id."
            )
        if normalized_resource_type not in resource_types:
            allowed = ", ".join(resource_types) or "none"
            raise SecretPolicyError(
                f"Secret logical name `{normalized_logical_name}` for app `{app_id}` does not allow resource_type "
                f"`{normalized_resource_type}`. Allowed resource types: {allowed}."
            )
        return
    if normalized_resource_type or normalized_resource_id:
        raise SecretPolicyError(
            f"Secret logical name `{normalized_logical_name}` for app `{app_id}` is workspace-scoped and must not include "
            "resource_type or resource_id."
        )


def assert_app_backend_targets_match_consumers(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    actions: list[str],
    target_patterns: list[str] | None,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> None:
    """Require app.backend target patterns to overlap declared consumer targets."""
    normalized_actions = {str(action).strip().lower() for action in actions}
    if APP_BACKEND_ACTION not in normalized_actions:
        return
    normalized_logical_name = str(logical_name or "").strip().lower()
    consumer = enabled_app_secret_consumers(state, workspace_id=workspace_id, app_id=app_id).get(normalized_logical_name)
    resource_types = _consumer_resource_types(consumer or {})
    consumer_targets = _consumer_targets(consumer)
    if not consumer_targets:
        raise SecretPolicyError(f"App `{app_id}` has no declared consumers for secret logical name `{normalized_logical_name}`.")
    for pattern in normalize_target_patterns_or_wildcard(target_patterns):
        if pattern in {"*", "maverick://app.backend/*"}:
            continue
        _assert_resource_target_matches_grant_scope(
            app_id=app_id,
            logical_name=normalized_logical_name,
            pattern=pattern,
            resource_types=resource_types,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        if not any(_target_overlaps(pattern, consumer_target) for consumer_target in consumer_targets):
            raise SecretPolicyError(
                f"App `{app_id}` does not declare a secret consumer matching target `{pattern}` for `{normalized_logical_name}`."
            )


def consumer_requires_secret(consumer: SecretConsumer) -> bool:
    """Return whether one consumer record has at least one delivery surface."""
    return bool(consumer.get("backend") or consumer.get("cli_commands") or consumer.get("mcp_tools"))


def _declared_secret_logical_names(values: list[str]) -> list[str]:
    return sorted({str(item).strip().lower() for item in values if str(item).strip()})


def _consumer_record(consumers: SecretConsumersByLogicalName, logical_name: str) -> SecretConsumer:
    return consumers.setdefault(
        logical_name,
        {
            "backend": False,
            "cli_commands": [],
            "mcp_tools": [],
            "resource_scoped": False,
            "resource_types": [],
        },
    )


def _record_consumer_resource_scope(consumer: SecretConsumer, resource_type: str | None) -> None:
    normalized = _normalize_optional_resource(resource_type)
    if not normalized:
        return
    consumer["resource_scoped"] = True
    resource_types = consumer.get("resource_types")
    if isinstance(resource_types, list) and normalized not in resource_types:
        resource_types.append(normalized)


def _consumer_resource_types(consumer: SecretConsumer) -> list[str]:
    values = consumer.get("resource_types")
    if not isinstance(values, list):
        return []
    return sorted({str(item).strip().lower() for item in values if str(item).strip()})


def _consumer_targets(consumer: SecretConsumer | None) -> list[str]:
    if not consumer:
        return []
    targets: list[str] = []
    resource_types = _consumer_resource_types(consumer)
    if consumer.get("backend"):
        _append_consumer_targets(targets, "backend", resource_types=resource_types)
    for command in consumer.get("cli_commands", []):
        _append_consumer_targets(targets, f"cli/{command}", resource_types=resource_types)
    for tool in consumer.get("mcp_tools", []):
        _append_consumer_targets(targets, f"mcp/{tool}", resource_types=resource_types)
    return targets


def _append_consumer_targets(targets: list[str], surface: str, *, resource_types: list[str]) -> None:
    surface_targets = [app_secret_target(surface)]
    surface_targets.extend(
        app_secret_target(surface, resource_type=resource_type, resource_id="*") for resource_type in resource_types
    )
    for target in surface_targets:
        if target not in targets:
            targets.append(target)


def _target_overlaps(pattern: str, target: str) -> bool:
    if pattern == "*" or target == "*" or pattern == target:
        return True
    try:
        return target_allowed(target, [pattern]) or target_allowed(pattern, [target])
    except SecretError:
        return pattern == target


def _assert_resource_target_matches_grant_scope(
    *,
    app_id: str,
    logical_name: str,
    pattern: str,
    resource_types: list[str],
    resource_type: str | None,
    resource_id: str | None,
) -> None:
    target_scope = _resource_scope_from_target(pattern, resource_types=resource_types)
    if target_scope is None:
        return
    target_resource_type, target_resource_id = target_scope
    grant_resource_type = _normalize_target_segment(resource_type)
    grant_resource_id = _normalize_target_segment(resource_id)
    if (
        not grant_resource_type
        or not grant_resource_id
        or target_resource_type != grant_resource_type
        or (target_resource_id not in {"*", grant_resource_id})
    ):
        raise SecretPolicyError(
            f"App `{app_id}` target `{pattern}` for `{logical_name}` does not match grant resource scope."
        )


def _resource_scope_from_target(pattern: str, *, resource_types: list[str]) -> tuple[str, str] | None:
    if not resource_types:
        return None
    parsed = urlsplit(pattern)
    if parsed.scheme.lower() != "maverick" or (parsed.hostname or "").lower() != "app.backend":
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 3:
        return None
    allowed_resource_types = {_normalize_target_segment(resource_type) for resource_type in resource_types}
    resource_type_segment = _normalize_target_segment(segments[-2])
    if resource_type_segment not in allowed_resource_types:
        return None
    return resource_type_segment, _normalize_target_segment(segments[-1])


def _normalize_optional_resource(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def _normalize_target_segment(value: str | None) -> str:
    return str(value or "").strip().lower().replace("_", "-")
