"""Persistence adapter administration CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.api.persistence_admin import (
    apply_persistence_migration,
    dry_run_persistence_migration,
    persistence_status_payload,
)
from core.cli.core_command_helpers import GLOBAL_AGENT_SAFE, core_cli_command
from core.cli.models import CliCommandDefinition, CliInvocationContext, CliInvocationPolicy


PLATFORM_ADMIN = CliInvocationPolicy(False, "admin", False, False, False)


def persistence_command_specs(*, start_path: Path | None = None) -> list[tuple[CliCommandDefinition, Any]]:
    """Build core-owned persistence adapter command specs."""
    repository_root = start_path

    def _repository_root() -> Path:
        return Path.cwd() if repository_root is None else repository_root

    def _status_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        root = _repository_root()
        settings = ControlStoreSettings.from_environment(repository_root=root)
        collections = build_control_plane_collections(settings)
        return persistence_status_payload(
            repository_root=root,
            active_settings=settings,
            active_collections=collections,
        )

    def _dry_run_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        root = _repository_root()
        settings = ControlStoreSettings.from_environment(repository_root=root)
        collections = build_control_plane_collections(settings)
        return dry_run_persistence_migration(
            repository_root=root,
            source_settings=settings,
            source_collections=collections,
            target_payload=arguments,
        )

    def _apply_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        root = _repository_root()
        settings = ControlStoreSettings.from_environment(repository_root=root)
        collections = build_control_plane_collections(settings)
        return apply_persistence_migration(
            repository_root=root,
            source_settings=settings,
            source_collections=collections,
            target_payload=arguments,
        )

    return [
        (
            core_cli_command(
                command_id="core.persistence.status",
                path_segments=["core", "persistence", "status"],
                description="Inspect the active control-plane persistence adapter.",
                owner_id="persistence",
                invocation_policy=GLOBAL_AGENT_SAFE,
            ),
            _status_handler,
        ),
        (
            core_cli_command(
                command_id="core.persistence.migration-dry-run",
                path_segments=["core", "persistence", "migration-dry-run"],
                description="Validate a full control-plane adapter migration plan.",
                owner_id="persistence",
                invocation_policy=PLATFORM_ADMIN,
            ),
            _dry_run_handler,
        ),
        (
            core_cli_command(
                command_id="core.persistence.migration-apply",
                path_segments=["core", "persistence", "migration-apply"],
                description="Copy all control-plane data to a target adapter and prepare cutover.",
                owner_id="persistence",
                invocation_policy=PLATFORM_ADMIN,
            ),
            _apply_handler,
        ),
    ]
