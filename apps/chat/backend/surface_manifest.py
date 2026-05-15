"""Agent-facing Chat CLI/MCP operations manifest."""

from __future__ import annotations

OPERATIONS_MANIFEST = {
    "app_id": "chat",
    "schema_version": "1",
    "default_action": "operations.manifest",
    "recommended": [
        {
            "task": "discover_chat_operations",
            "operation": "operations.manifest",
            "calls_required": 1,
        },
        {
            "task": "list_chat_projects",
            "operation": "projects.list",
            "calls_required": 1,
        },
        {
            "task": "search_chat_project_references",
            "operation": "references.search",
            "calls_required": 1,
        },
        {
            "task": "read_or_update_chat_view_filter",
            "operation": "view_filter / set_view_filter / set_custom_view / clear_custom_view",
            "calls_required": 1,
        },
    ],
    "operations": {
        "projects.list": {
            "description": "Return the compact Chat project catalog and current view preferences.",
            "required_fields": [],
            "payload_profile": "compact",
        },
        "references.manifest": {
            "description": "Describe Chat reference entity types.",
            "required_fields": [],
            "payload_profile": "compact",
        },
        "references.search": {
            "description": "Search Chat project references without loading runtime transcripts.",
            "required_fields": ["entity_type"],
            "accepted_aliases": {"entity_type": ["type"], "query": ["q"]},
            "payload_profile": "compact",
        },
        "references.resolve": {
            "description": "Resolve one Chat project reference by id.",
            "required_fields": ["entity_type", "entity_id"],
            "accepted_aliases": {"entity_type": ["type"], "entity_id": ["project_id", "id"]},
            "payload_profile": "full_by_id",
        },
        "references.summarize": {
            "description": "Return a token-efficient summary for one Chat project reference.",
            "required_fields": ["entity_type", "entity_id"],
            "accepted_aliases": {"entity_type": ["type"], "entity_id": ["project_id", "id"]},
            "payload_profile": "compact",
        },
        "view_filter": {
            "description": "Read the persisted Chat project/thread browse filter.",
            "required_fields": [],
            "payload_profile": "compact",
        },
        "set_view_filter": {
            "description": "Set Chat browse query filters.",
            "required_fields": [],
            "payload_profile": "compact",
        },
        "set_custom_view": {
            "description": "Show a curated Chat project/thread reference set.",
            "required_fields": ["refs"],
            "payload_profile": "compact",
        },
        "clear_custom_view": {
            "description": "Return Chat to normal project/thread browsing mode.",
            "required_fields": [],
            "payload_profile": "compact",
        },
    },
    "id_patterns": {
        "project": "Chat project UUID stored as project_id/entity_id.",
        "thread": "Core runtime thread id; Chat view filters may reference it but Chat does not own thread records.",
    },
    "payload_profiles": {
        "default": "compact operations manifest",
        "projects.list": "project_id, name, created_at, updated_at, preferences",
        "references.search": "reference rows only; no transcripts or messages",
        "references.resolve": "one reference row by explicit id",
    },
    "examples": {
        "cli_manifest": {
            "command": "maverick app chat cli run chat --json",
        },
        "cli_search_projects": {
            "command": "maverick app chat cli run chat --json --action references.search --entity-type project --query client",
        },
        "mcp_search_projects": {
            "tool": "chat_reference_search",
            "arguments": {"entity_type": "project", "query": "client", "limit": 10},
        },
        "mcp_operations_manifest": {
            "tool": "chat_operations_manifest",
            "arguments": {},
        },
    },
    "notes": [
        "Runtime threads, messages, turns, and cleanup are core runtime concerns.",
        "Chat CLI/MCP operations only expose app-owned project references and view state.",
    ],
}
