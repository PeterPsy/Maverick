"""Compact machine-facing operation manifest for the Agents app."""

from __future__ import annotations


OPERATIONS_MANIFEST = {
    "app_id": "agents",
    "schema_version": "2",
    "default_action": "operations.manifest",
    "operations": {
        "catalog.compact": {
            "description": "List agents without instruction content.",
            "optional": ["query", "limit"],
        },
        "catalog": {"description": "Return the full agent catalog."},
        "get_agent_definition": {
            "description": "Return one self-contained agent definition.",
            "required": ["id"],
        },
        "upsert_agent_definition": {
            "description": "Create or update one self-contained agent definition.",
            "required": ["id", "name", "instructions"],
            "optional": ["description", "skill_ids", "enabled"],
        },
        "delete_agent_definition": {
            "description": "Delete one agent definition.",
            "required": ["id"],
        },
    },
    "id_pattern": "agent-type-[a-z0-9]+(-[a-z0-9]+)*",
    "policy": {
        "sandbox_agent_allowed": True,
        "requires_workspace_context": True,
        "requires_full_access": False,
    },
}
