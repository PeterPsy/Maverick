"""Compact machine-facing operation manifest for the Agents app."""

from __future__ import annotations


OPERATIONS_MANIFEST = {
    "app_id": "agents",
    "schema_version": "1",
    "default_action": "operations.manifest",
    "recommended": [
        {
            "task": "create_or_update_agent_definition",
            "operation": "upsert_agent_definition",
            "mcp_tool": "agents_upsert_agent_definition",
            "calls_required": 1,
        },
        {
            "task": "browse_agent_catalog",
            "operation": "catalog.compact",
            "calls_required": 1,
        },
        {
            "task": "read_full_agent_definition",
            "operation": "get_agent_definition",
            "calls_required": 1,
        },
    ],
    "operations": {
        "operations.manifest": {
            "description": "Return this compact operation manifest.",
            "required": [],
            "payload_profile": "compact",
        },
        "catalog.compact": {
            "description": "List roles and agent types without long instructions or common prompt content.",
            "required": [],
            "optional": ["entity_type", "query", "limit"],
            "payload_profile": "compact",
        },
        "catalog": {
            "description": "Return the full legacy catalog, including common prompt and role instructions.",
            "required": [],
            "payload_profile": "full",
        },
        "get_agent_definition": {
            "description": "Return one full agent definition by agent type id.",
            "required": ["id"],
            "aliases": {"id": ["agent_type_id", "entity_id"]},
            "optional": ["include_common_prompt"],
            "payload_profile": "content",
        },
        "upsert_agent_definition": {
            "description": "Create or update the role prompt and agent type in one idempotent call.",
            "required": ["id", "name", "instructions"],
            "aliases": {
                "id": ["agent_type_id", "entity_id"],
                "instructions": ["role_instructions", "prompt"],
                "role_id": ["role_prompt_id"],
            },
            "optional": [
                "description",
                "role_id",
                "role_description",
                "skill_ids",
                "skill_activation_mode",
                "trace_verbosity",
                "enabled",
                "common_prompt",
                "include_content",
            ],
            "payload_profile": "compact",
        },
        "preview_prompt": {
            "description": "Render the composed prompt for one agent type.",
            "required": ["agent_type_id"],
            "payload_profile": "content",
        },
    },
    "payload_profiles": {
        "default": "compact_manifest",
        "catalog.compact": "compact_identity_and_runtime_selection_metadata",
        "catalog": "full_catalog_with_prompt_content",
        "get_agent_definition": "full_single_record_by_id",
        "upsert_agent_definition": "compact_write_result_by_default",
    },
    "id_patterns": {
        "agent_type_id": "agent-type-[a-z0-9]+(-[a-z0-9]+)*",
        "role_id": "[a-z0-9]+(-[a-z0-9]+)*",
    },
    "examples": {
        "cli_manifest": "maverick app agents cli run agents --json",
        "cli_upsert": (
            "maverick app agents cli run agents --arguments-json "
            "'{\"action\":\"upsert_agent_definition\",\"id\":\"agent-type-example-specialist\","
            "\"name\":\"Example Specialist\",\"instructions\":\"# Example Specialist\\n\\nHandle one focused task.\"}' --json"
        ),
        "mcp_upsert": (
            "maverick app agents mcp call agents_upsert_agent_definition --arguments-json "
            "'{\"id\":\"agent-type-example-specialist\",\"name\":\"Example Specialist\","
            "\"instructions\":\"# Example Specialist\\n\\nHandle one focused task.\"}' --json"
        ),
    },
    "policy": {
        "sandbox_agent_allowed": True,
        "requires_workspace_context": True,
        "requires_full_access": False,
    },
}
