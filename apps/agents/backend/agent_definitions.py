"""Agent definition operations for compact app surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_runtime_revision import agent_runtime_revision
from store import (
    AgentsValidationError,
    get_agent_definition as load_agent_definition,
    list_agent_definitions,
    save_agent_definition,
    validate_agent_type_id,
)


UPSERT_ERROR_HINT = {
    "expected_fields": ["id", "name", "instructions"],
    "example": {
        "action": "upsert_agent_definition",
        "id": "agent-type-example-specialist",
        "name": "Example Specialist",
        "instructions": "Handle one focused class of work.",
    },
}


def compact_catalog(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    query = str(body.get("query") or body.get("q") or "").strip().casefold()
    limit = _bounded_int(body.get("limit"), default=50, minimum=1, maximum=100)
    agents = [_compact_agent(item) for item in list_agent_definitions(data_root)]
    if query:
        agents = [item for item in agents if _matches_query(item, query)]
    return {
        "app_id": "agents",
        "schema_version": "2",
        "payload_profile": "compact",
        "count": len(agents),
        "agent_types": agents[:limit],
        "limit": limit,
    }


def catalog(data_root: Path) -> dict[str, Any]:
    return {"agent_types": [_full_agent(item) for item in list_agent_definitions(data_root)]}


def get_agent_definition(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    agent_id = _agent_id_from_body(body)
    agent = load_agent_definition(data_root, agent_id)
    if agent is None:
        return {"exists": False, "agent_type_id": agent_id}
    return {"exists": True, "agent_definition": _full_agent(agent)}


def upsert_agent_definition(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    agent_id = _agent_id_from_body(body)
    existing = load_agent_definition(data_root, agent_id)
    name = _text_field(body, "name", default=(existing or {}).get("name"))
    instructions = _text_field(
        body,
        "instructions",
        default=(existing or {}).get("instructions"),
        preserve_whitespace=True,
    )
    description = _text_field(
        body,
        "description",
        default=(existing or {}).get("description") or "",
        required=False,
    )
    skill_ids = _skill_ids(
        body.get("skill_ids"),
        default=(existing or {}).get("skill_ids", []),
    )
    candidate = {
        "id": agent_id,
        "name": name,
        "description": description,
        "instructions": instructions,
        "skill_ids": skill_ids,
        "enabled": bool(body.get("enabled", (existing or {}).get("enabled", True))),
    }
    changed = existing is None or any(
        existing.get(key) != value for key, value in candidate.items()
    )
    agent = save_agent_definition(data_root, candidate) if changed else existing
    if agent is None:
        raise AgentsValidationError("Agent definition was not saved.")
    return {
        "operation": "upsert_agent_definition",
        "created": existing is None,
        "changed": changed,
        "agent_definition": _full_agent(agent),
    }


def _agent_id_from_body(body: dict[str, Any]) -> str:
    raw = str(body.get("id") or body.get("agent_type_id") or "").strip()
    if not raw:
        raise AgentsValidationError("Missing required field: id")
    if not raw.startswith("agent-type-"):
        raw = f"agent-type-{raw}"
    return validate_agent_type_id(raw)


def _text_field(
    body: dict[str, Any],
    key: str,
    *,
    default: Any = None,
    required: bool = True,
    preserve_whitespace: bool = False,
) -> str:
    value = body.get(key, default)
    text = str(value or "").strip()
    if not preserve_whitespace:
        text = " ".join(text.split())
    if required and not text:
        raise AgentsValidationError(f"Missing required field: {key}")
    return text


def _skill_ids(value: Any, *, default: list[str]) -> list[str]:
    selected = default if value is None else value
    if not isinstance(selected, list):
        raise AgentsValidationError("Field `skill_ids` must be a list.")
    return list(dict.fromkeys(
        str(item).strip() for item in selected if str(item).strip()
    ))


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError) as error:
        raise AgentsValidationError("Field `limit` must be an integer.") from error
    return max(minimum, min(parsed, maximum))


def _compact_agent(agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": agent["id"],
        "name": agent["name"],
        "description": agent.get("description", ""),
        "skill_ids": agent.get("skill_ids", []),
        "skill_count": len(agent.get("skill_ids", [])),
        "enabled": bool(agent.get("enabled", True)),
        "updated_at": agent.get("updated_at", ""),
        "revision_id": agent_runtime_revision(agent),
    }


def _full_agent(agent: dict[str, Any]) -> dict[str, Any]:
    return {**_compact_agent(agent), "instructions": agent["instructions"], "created_at": agent.get("created_at", "")}


def _matches_query(item: dict[str, Any], query: str) -> bool:
    return any(
        query in str(item.get(field, "")).casefold()
        for field in ("id", "name", "description")
    )
