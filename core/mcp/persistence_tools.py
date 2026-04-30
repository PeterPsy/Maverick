"""Persistence adapter administration MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.api.persistence_admin import (
    apply_persistence_migration,
    dry_run_persistence_migration,
    persistence_status_payload,
)
from core.mcp.core_tool_helpers import OPERATOR_ONLY, WORKSPACE_SAFE, core_mcp_tool
from core.mcp.models import McpInvocationContext, McpToolDefinition


def persistence_tool_specs(*, start_path: Path | None = None) -> list[tuple[McpToolDefinition, Any]]:
    """Build core-owned persistence adapter MCP tool specs."""
    repository_root = start_path

    def _repository_root() -> Path:
        return Path.cwd() if repository_root is None else repository_root

    def _status_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        root = _repository_root()
        settings = ControlStoreSettings.from_environment(repository_root=root)
        collections = build_control_plane_collections(settings)
        return persistence_status_payload(
            repository_root=root,
            active_settings=settings,
            active_collections=collections,
        )

    def _dry_run_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        root = _repository_root()
        settings = ControlStoreSettings.from_environment(repository_root=root)
        collections = build_control_plane_collections(settings)
        return dry_run_persistence_migration(
            repository_root=root,
            source_settings=settings,
            source_collections=collections,
            target_payload=arguments,
        )

    def _apply_handler(arguments: dict[str, Any], context: McpInvocationContext) -> dict[str, Any]:
        root = _repository_root()
        settings = ControlStoreSettings.from_environment(repository_root=root)
        collections = build_control_plane_collections(settings)
        return apply_persistence_migration(
            repository_root=root,
            source_settings=settings,
            source_collections=collections,
            target_payload=arguments,
        )

    migration_schema = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["json", "mongo"]},
            "json_root": {"type": "string"},
            "mongodb_uri": {"type": "string"},
            "mongodb_database": {"type": "string"},
        },
        "required": ["kind"],
    }
    return [
        (
            core_mcp_tool(
                tool_name="core.persistence.status",
                description="Inspect the active control-plane persistence adapter.",
                owner_id="persistence",
                invocation_policy=WORKSPACE_SAFE,
                input_schema={"type": "object"},
            ),
            _status_handler,
        ),
        (
            core_mcp_tool(
                tool_name="core.persistence.migration.dry_run",
                description="Validate a full control-plane adapter migration plan.",
                owner_id="persistence",
                invocation_policy=OPERATOR_ONLY,
                input_schema=migration_schema,
            ),
            _dry_run_handler,
        ),
        (
            core_mcp_tool(
                tool_name="core.persistence.migration.apply",
                description="Copy all control-plane data to a target adapter and prepare cutover.",
                owner_id="persistence",
                invocation_policy=OPERATOR_ONLY,
                input_schema=migration_schema,
            ),
            _apply_handler,
        ),
    ]
