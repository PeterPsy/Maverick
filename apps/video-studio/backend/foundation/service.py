"""Shared application service for foundation backend, CLI, MCP, and sidecar."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .database import FoundationDatabase, FoundationDatabaseError, LATEST_SCHEMA_VERSION


APP_ID = "video-studio"
APP_VERSION = "0.2.0"
FOUNDATION_ACTIONS = ("status", "schema", "health", "capabilities")


class FoundationServiceError(RuntimeError):
    """Stable surface error with no filesystem details."""


class FoundationService:
    """Expose only the implemented Video Studio foundation behavior."""

    def __init__(self, data_root: str | Path) -> None:
        try:
            self.database = FoundationDatabase(data_root, create_data_root=False)
        except FoundationDatabaseError as error:
            raise FoundationServiceError(str(error)) from error

    def dispatch(self, action: str) -> dict[str, Any]:
        normalized = str(action or "status").strip().lower()
        try:
            if normalized == "status":
                schema = self.database.schema_status()
                return {
                    "app_id": APP_ID,
                    "app_version": APP_VERSION,
                    "status": "ready",
                    "schema_version": schema["schema_version"],
                    "journal_mode": schema["journal_mode"],
                }
            if normalized == "schema":
                return {"app_id": APP_ID, **self.database.schema_status()}
            if normalized == "health":
                return {"app_id": APP_ID, **self.database.health()}
            if normalized == "capabilities":
                return foundation_manifest()
        except FoundationDatabaseError as error:
            raise FoundationServiceError(str(error)) from error
        raise FoundationServiceError(f"Unsupported foundation action `{normalized}`.")


def foundation_manifest() -> dict[str, Any]:
    """Describe concrete checkpoint surfaces, not future editing capabilities."""
    return {
        "app_id": APP_ID,
        "foundation_version": "3",
        "storage": {"kind": "sqlite", "schema_version": LATEST_SCHEMA_VERSION},
        "actions": [
            *FOUNDATION_ACTIONS,
            "project.create", "project.list", "project.get", "project.rename",
            "project.duplicate", "project.archive", "project.restore",
            "revision.get", "revision.compare", "native.export", "native.import",
            "operations.apply", "history.undo", "history.redo",
        ],
        "surfaces": {
            "backend": [*FOUNDATION_ACTIONS, *(
                "project.create", "project.list", "project.get", "project.rename",
                "project.duplicate", "project.archive", "project.restore",
                "revision.get", "revision.compare", "native.export", "native.import",
                "operations.apply", "history.undo", "history.redo",
            )],
            "cli": ["video-studio"],
            "mcp": [
                "video_studio_foundation", "video_studio_reference_manifest",
                "video_studio_project_create", "video_studio_project_list",
                "video_studio_project_get", "video_studio_project_rename",
                "video_studio_project_duplicate", "video_studio_project_archive",
                "video_studio_project_restore", "video_studio_revision_get",
                "video_studio_revision_compare", "video_studio_native_export",
                "video_studio_native_import", "video_studio_operations_apply",
                "video_studio_undo", "video_studio_redo",
            ],
            "lifecycle": ["install", "migrate", "health_check"],
        },
        "domain_capabilities": [
            "project-ir.v1",
            "revision-engine.v1",
            "typed-editing.v1",
            "native-interchange.v1",
        ],
    }
