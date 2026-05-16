"""Compact Storage CLI and MCP operations manifest."""

from __future__ import annotations

from typing import Any


STORAGE_ACTIONS = [
    "operations.manifest",
    "catalog",
    "view_filter",
    "set_view_filter",
    "set_custom_view",
    "clear_custom_view",
    "file_info",
    "read_file",
    "write_file",
    "file.content.read",
    "file.content.write",
    "upload_file",
    "preview_text",
    "file.preview.text",
    "preview_table",
    "file.preview.table",
    "render_preview",
    "file.preview.render",
    "render_thumbnail",
    "update_markdown_file",
    "create_folder",
    "read_folder",
    "download_folder",
    "delete_folder",
    "move_file",
    "move_folder",
    "move_items",
    "delete_file",
    "references.manifest",
    "references.search",
    "references.resolve",
    "references.summarize",
    "health.check",
]

STORAGE_ACTION_ALIASES = {
    "write": "file.content.write",
    "write-file": "file.content.write",
    "write-content": "file.content.write",
    "read_file": "file.content.read",
}


def operations_manifest_payload() -> dict[str, Any]:
    """Return the compact agent-facing contract for Storage operations."""
    return {
        "app_id": "storage",
        "schema_version": "1",
        "default_action": "operations.manifest",
        "commands": [
            {
                "surface": "cli",
                "name": "storage",
                "description": "Inspect, search, preview, read, write, move, and delete workspace Storage files.",
            }
        ],
        "tools": [
            {
                "surface": "mcp",
                "name": "maverick_storage",
                "description": "Generic Storage operation runner for less common actions.",
            },
            {"surface": "mcp", "name": "storage_list_files", "operation": "catalog"},
            {"surface": "mcp", "name": "storage_file_info", "operation": "file_info"},
            {"surface": "mcp", "name": "storage_read_file", "operation": "file.content.read"},
            {"surface": "mcp", "name": "storage_preview_text", "operation": "file.preview.text"},
            {"surface": "mcp", "name": "storage_preview_table", "operation": "file.preview.table"},
            {"surface": "mcp", "name": "storage_write_file", "operation": "file.content.write"},
            {"surface": "mcp", "name": "storage_reference_search", "operation": "references.search"},
            {"surface": "mcp", "name": "storage_reference_resolve", "operation": "references.resolve"},
            {"surface": "mcp", "name": "storage_reference_summarize", "operation": "references.summarize"},
        ],
        "recommended": [
            {
                "task": "list_workspace_files",
                "operation": "catalog",
                "calls_required": 1,
                "example": {"action": "catalog", "limit": 20},
            },
            {
                "task": "read_one_file",
                "operation": "file.content.read",
                "calls_required": 1,
                "example": {"action": "file.content.read", "workspace_relative_path": "storage/generated/report.md"},
            },
            {
                "task": "create_or_overwrite_generated_file",
                "operation": "file.content.write",
                "calls_required": 1,
                "example": {
                    "action": "file.content.write",
                    "workspace_relative_path": "storage/generated/report.md",
                    "mode": "overwrite",
                    "content": "# Report",
                },
            },
        ],
        "operations": [
            {
                "action": "catalog",
                "description": "List files and folders from the workspace Storage inventory.",
                "optional": [
                    "query",
                    "role",
                    "kind",
                    "folder_path",
                    "file_ids",
                    "workspace_relative_paths",
                    "offset",
                    "limit",
                ],
                "payload_profile": "paginated_metadata",
            },
            {
                "action": "file_info",
                "description": "Return metadata for one file by role/path or workspace_relative_path.",
                "required_any": ["workspace_relative_path", "role + relative_path"],
                "payload_profile": "single_record_metadata",
            },
            {
                "action": "file.content.read",
                "aliases": ["read_file"],
                "description": "Read one file as bounded base64 content.",
                "required_any": ["workspace_relative_path", "role + relative_path"],
                "optional": ["max_bytes"],
                "payload_profile": "explicit_content",
            },
            {
                "action": "file.content.write",
                "aliases": ["write", "write_file", "write-file", "write-content"],
                "description": "Create or overwrite one workspace Storage file.",
                "required_any": ["workspace_relative_path", "role + relative_path"],
                "required_one_of": ["content", "content_base64"],
                "optional": ["mode"],
                "payload_profile": "single_write_result",
            },
            {
                "action": "preview_text",
                "description": "Extract a bounded text preview for supported files.",
                "required_any": ["workspace_relative_path", "role + relative_path"],
                "optional": ["max_chars"],
                "payload_profile": "bounded_preview",
            },
            {
                "action": "references.search",
                "description": "Search Storage file or folder app references.",
                "optional": ["query", "entity_type", "limit"],
                "payload_profile": "compact_references",
            },
            {
                "action": "references.resolve",
                "description": "Resolve one Storage file or folder app reference.",
                "required": ["entity_id"],
                "optional": ["entity_type"],
                "payload_profile": "single_reference",
            },
        ],
        "payload_profiles": {
            "operations.manifest": "compact_default",
            "catalog": "explicit_action_paginated",
            "file_info": "metadata_only",
            "file.content.read": "explicit_file_content_only",
            "preview_text": "bounded_preview_only",
            "references.search": "compact_results",
        },
        "aliases": STORAGE_ACTION_ALIASES,
        "id_patterns": {
            "file_id": "file_<uuid>",
            "folder_id": "<role>:<percent-encoded-relative-path>/",
            "workspace_relative_path": "storage/(uploaded|generated)/<relative-path>",
        },
        "policy": {
            "sandbox_agent_allowed": True,
            "requires_workspace_context": True,
            "requires_full_access": False,
        },
    }
