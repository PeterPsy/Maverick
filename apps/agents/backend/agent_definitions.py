"""Agent definition operations for compact agent-facing surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from models import TRACE_VERBOSITIES
from store import (
    AgentsValidationError,
    get_agent_type,
    get_role,
    list_agent_types,
    list_roles,
    read_common_prompt,
    save_agent_type,
    save_role,
    validate_agent_type_id,
    validate_role_id,
    write_common_prompt,
)


UPSERT_ERROR_HINT = {
    "expected_fields": ["id", "name", "instructions"],
    "accepted_aliases": {
        "id": ["agent_type_id", "entity_id"],
        "instructions": ["role_instructions", "prompt"],
        "role_id": ["role_prompt_id"],
    },
    "allowed_values": {"trace_verbosity": sorted(TRACE_VERBOSITIES)},
    "example": {
        "action": "upsert_agent_definition",
        "id": "agent-type-example-specialist",
        "name": "Example Specialist",
        "instructions": "# Example Specialist\n\nHandle one focused class of work.",
    },
}


def compact_catalog(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    """Return a compact, paginated catalog without long prompt content."""
    entity_type = _optional_entity_type(body)
    query = str(body.get("query") or body.get("q") or "").strip().casefold()
    limit = _bounded_int(body.get("limit"), default=50, minimum=1, maximum=100)
    roles = [_compact_role(item) for item in list_roles(data_root)]
    agent_types = [_compact_agent_type(item) for item in list_agent_types(data_root)]
    if query:
        roles = [item for item in roles if _matches_query(item, query)]
        agent_types = [item for item in agent_types if _matches_query(item, query)]
    if entity_type == "role_prompt":
        agent_types = []
    if entity_type == "agent_type":
        roles = []
    return {
        "app_id": "agents",
        "schema_version": "1",
        "payload_profile": "compact",
        "counts": {"roles": len(roles), "agent_types": len(agent_types)},
        "roles": roles[:limit],
        "agent_types": agent_types[:limit],
        "limit": limit,
    }


def get_agent_definition(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    """Return one full agent definition by agent type id."""
    agent_type_id = _agent_type_id_from_body(body)
    agent_type = get_agent_type(data_root, agent_type_id)
    if agent_type is None:
        return {"exists": False, "agent_type_id": agent_type_id}
    role = get_role(data_root, agent_type["role_id"])
    if role is None:
        raise AgentsValidationError(f"Unknown role id: {agent_type['role_id']}")
    payload = {
        "exists": True,
        "agent_definition": _definition_payload(agent_type=agent_type, role=role, include_content=True),
    }
    if bool(body.get("include_common_prompt")):
        payload["common_prompt"] = read_common_prompt(data_root)
    return payload


def upsert_agent_definition(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    """Create or update the role prompt and agent type in one idempotent operation."""
    agent_type_id = _agent_type_id_from_body(body)
    existing_agent_type = get_agent_type(data_root, agent_type_id)
    role_id = _role_id_from_body(body, agent_type_id=agent_type_id, existing_agent_type=existing_agent_type)
    existing_role = get_role(data_root, role_id)
    name = _text_field(body, "name", default=(existing_agent_type or {}).get("name"))
    instructions = _text_field(
        body,
        "instructions",
        aliases=("role_instructions", "prompt"),
        default=(existing_role or {}).get("instructions"),
    )
    description = _text_field(
        body,
        "description",
        default=(existing_agent_type or {}).get("description") or f"Agent definition for {name}.",
        required=False,
    )
    role_description = _text_field(
        body,
        "role_description",
        default=(existing_role or {}).get("description") or description,
        required=False,
    )
    trace_verbosity = str(body.get("trace_verbosity") or (existing_agent_type or {}).get("trace_verbosity") or "compact")
    if trace_verbosity not in TRACE_VERBOSITIES:
        raise AgentsValidationError(f"Invalid trace_verbosity: {trace_verbosity}")
    skill_ids = _skill_ids(body.get("skill_ids"), default=(existing_agent_type or {}).get("skill_ids", []))
    enabled = bool(body.get("enabled", (existing_agent_type or {}).get("enabled", True)))

    role_candidate = {
        "id": role_id,
        "name": name,
        "description": role_description,
        "instructions": instructions,
    }
    agent_type_candidate = {
        "id": agent_type_id,
        "name": name,
        "description": description,
        "role_id": role_id,
        "skill_ids": skill_ids,
        "trace_verbosity": trace_verbosity,
        "enabled": enabled,
    }
    role_changed = existing_role is None or any(existing_role.get(key) != value for key, value in role_candidate.items())
    agent_type_changed = existing_agent_type is None or any(
        existing_agent_type.get(key) != value for key, value in agent_type_candidate.items()
    )
    role = save_role(data_root, role_candidate) if role_changed else existing_role
    agent_type = save_agent_type(data_root, agent_type_candidate) if agent_type_changed else existing_agent_type
    if role is None or agent_type is None:
        raise AgentsValidationError("Agent definition upsert failed to materialize saved records.")
    common_prompt_changed = False
    if "common_prompt" in body:
        next_common_prompt = str(body.get("common_prompt") or "").strip() + "\n"
        if read_common_prompt(data_root) != next_common_prompt:
            write_common_prompt(data_root, next_common_prompt)
            common_prompt_changed = True
    include_content = bool(body.get("include_content"))
    return {
        "operation": "upsert_agent_definition",
        "created": {"agent_type": existing_agent_type is None, "role": existing_role is None},
        "changed": {
            "agent_type": agent_type_changed,
            "role": role_changed,
            "common_prompt": common_prompt_changed,
        },
        "agent_definition": _definition_payload(
            agent_type=agent_type,
            role=role,
            include_content=include_content,
        ),
    }


def _agent_type_id_from_body(body: dict[str, Any]) -> str:
    raw = str(body.get("agent_type_id") or body.get("id") or body.get("entity_id") or "").strip()
    if not raw:
        raise AgentsValidationError("Missing required field: id")
    if not raw.startswith("agent-type-"):
        raw = f"agent-type-{raw}"
    return validate_agent_type_id(raw)


def _role_id_from_body(
    body: dict[str, Any],
    *,
    agent_type_id: str,
    existing_agent_type: dict[str, Any] | None,
) -> str:
    raw = str(
        body.get("role_id")
        or body.get("role_prompt_id")
        or (existing_agent_type or {}).get("role_id")
        or agent_type_id.removeprefix("agent-type-")
    ).strip()
    return validate_role_id(raw)


def _text_field(
    body: dict[str, Any],
    key: str,
    *,
    aliases: tuple[str, ...] = (),
    default: Any = None,
    required: bool = True,
) -> str:
    value = body.get(key)
    for alias in aliases:
        if value is None:
            value = body.get(alias)
    if value is None:
        value = default
    text = " ".join(str(value or "").split()).strip() if key != "instructions" else str(value or "").strip()
    if required and not text:
        raise AgentsValidationError(f"Missing required field: {key}")
    return text


def _skill_ids(value: Any, *, default: list[str]) -> list[str]:
    if value is None:
        value = default
    if not isinstance(value, list):
        raise AgentsValidationError("Field `skill_ids` must be a list.")
    return [str(item).strip() for item in value if str(item).strip()]


def _optional_entity_type(body: dict[str, Any]) -> str:
    entity_type = str(body.get("entity_type") or body.get("type") or "").strip()
    if entity_type and entity_type not in {"agent_type", "role_prompt"}:
        raise AgentsValidationError(f"Unsupported reference entity type: {entity_type}")
    return entity_type


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError) as error:
        raise AgentsValidationError("Field `limit` must be an integer.") from error
    return max(minimum, min(parsed, maximum))


def _compact_role(role: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": role["id"],
        "name": role["name"],
        "description": role.get("description", ""),
    }


def _compact_agent_type(agent_type: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": agent_type["id"],
        "name": agent_type["name"],
        "description": agent_type.get("description", ""),
        "role_id": agent_type["role_id"],
        "skill_count": len(agent_type.get("skill_ids", [])),
        "trace_verbosity": agent_type.get("trace_verbosity", "compact"),
        "enabled": bool(agent_type.get("enabled", True)),
        "updated_at": agent_type.get("updated_at", ""),
    }


def _definition_payload(*, agent_type: dict[str, Any], role: dict[str, Any], include_content: bool) -> dict[str, Any]:
    payload = {
        "id": agent_type["id"],
        "name": agent_type["name"],
        "description": agent_type.get("description", ""),
        "role_id": role["id"],
        "role_name": role["name"],
        "role_description": role.get("description", ""),
        "skill_ids": agent_type.get("skill_ids", []),
        "trace_verbosity": agent_type.get("trace_verbosity", "compact"),
        "enabled": bool(agent_type.get("enabled", True)),
        "created_at": agent_type.get("created_at", ""),
        "updated_at": agent_type.get("updated_at", ""),
    }
    if include_content:
        payload["instructions"] = role.get("instructions", "")
    return payload


def _matches_query(item: dict[str, Any], query: str) -> bool:
    return any(query in str(item.get(field, "")).casefold() for field in ("id", "name", "description", "role_id"))
