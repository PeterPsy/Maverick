"""JSON-backed storage for self-contained agent definitions."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from core.app_sdk.storage import read_json_state, write_json_state
from models import AGENT_TYPE_ID_PATTERN


class AgentsValidationError(ValueError):
    """Raised when app-owned agent data is invalid."""


def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def agents_path(data_root: Path) -> Path:
    return data_root / "agents.json"


def ensure_data_root(data_root: Path) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    if not agents_path(data_root).exists():
        write_agent_definitions(data_root, [])


def validate_agent_type_id(agent_type_id: str) -> str:
    normalized = str(agent_type_id or "").strip()
    if not AGENT_TYPE_ID_PATTERN.fullmatch(normalized):
        raise AgentsValidationError(f"Invalid agent id: {normalized}")
    return normalized


def normalize_agent_definition(payload: dict) -> dict:
    agent_id = validate_agent_type_id(str(payload.get("id") or ""))
    name = " ".join(str(payload.get("name") or "").split()).strip()
    instructions = str(payload.get("instructions") or "").strip()
    if not name:
        raise AgentsValidationError("Agent name is required.")
    if not instructions:
        raise AgentsValidationError("Agent instructions are required.")
    raw_skills = payload.get("skill_ids")
    if raw_skills is not None and not isinstance(raw_skills, list):
        raise AgentsValidationError("Field `skill_ids` must be a list.")
    timestamp = now_timestamp()
    return {
        "id": agent_id,
        "name": name,
        "description": " ".join(str(payload.get("description") or "").split()).strip(),
        "instructions": instructions,
        "skill_ids": list(dict.fromkeys(
            str(skill_id).strip()
            for skill_id in (raw_skills or [])
            if str(skill_id).strip()
        )),
        "enabled": bool(payload.get("enabled", True)),
        "created_at": str(payload.get("created_at") or timestamp),
        "updated_at": str(payload.get("updated_at") or timestamp),
    }


def list_agent_definitions(data_root: Path) -> list[dict]:
    ensure_data_root(data_root)
    try:
        payload = read_json_state(data_root, "agents.json", {})
    except (ValueError, json.JSONDecodeError):
        payload = {}
    items = payload.get("agents") if isinstance(payload, dict) else None
    return [
        normalize_agent_definition(item)
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, dict)
    ]


def write_agent_definitions(data_root: Path, agents: list[dict]) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    write_json_state(
        data_root,
        "agents.json",
        {"schema_version": "2", "agents": agents},
    )


def get_agent_definition(data_root: Path, agent_id: str) -> dict | None:
    normalized = validate_agent_type_id(agent_id)
    return next(
        (item for item in list_agent_definitions(data_root) if item["id"] == normalized),
        None,
    )


def save_agent_definition(data_root: Path, payload: dict) -> dict:
    timestamp = now_timestamp()
    existing = get_agent_definition(data_root, str(payload.get("id") or ""))
    candidate = normalize_agent_definition(
        {
            **(existing or {}),
            **payload,
            "created_at": (existing or {}).get("created_at") or timestamp,
            "updated_at": timestamp,
        }
    )
    agents = [
        item
        for item in list_agent_definitions(data_root)
        if item["id"] != candidate["id"]
    ]
    agents.append(candidate)
    write_agent_definitions(
        data_root,
        sorted(agents, key=lambda item: item["name"].casefold()),
    )
    return candidate


def delete_agent_definition(data_root: Path, agent_id: str) -> bool:
    normalized = validate_agent_type_id(agent_id)
    original = list_agent_definitions(data_root)
    remaining = [item for item in original if item["id"] != normalized]
    write_agent_definitions(data_root, remaining)
    return len(remaining) != len(original)
