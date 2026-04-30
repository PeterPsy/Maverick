"""JSON and markdown-backed agents app storage."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from core.app_sdk.storage import read_json_state, write_json_state
from models import (
    AGENT_TYPE_ID_PATTERN,
    DEFAULT_COMMON_PROMPT,
    ROLE_ID_PATTERN,
    TRACE_VERBOSITIES,
)


class AgentsValidationError(ValueError):
    """Raised when app-owned agents data is invalid."""


def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def common_prompt_path(data_root: Path) -> Path:
    return data_root / "common_prompt.md"


def roles_root(data_root: Path) -> Path:
    return data_root / "roles"


def agent_types_path(data_root: Path) -> Path:
    return data_root / "agent_types.json"


def ensure_data_root(data_root: Path) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    roles_root(data_root).mkdir(parents=True, exist_ok=True)
    if not common_prompt_path(data_root).exists():
        common_prompt_path(data_root).write_text(DEFAULT_COMMON_PROMPT, encoding="utf-8")
    if not agent_types_path(data_root).exists():
        write_json(agent_types_path(data_root), {"schema_version": "1", "agent_types": []})


def write_json(path: Path, payload: dict) -> None:
    write_json_state(path.parent, path.name, payload)


def read_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return default
    try:
        payload = read_json_state(path.parent, path.name, default)
    except (ValueError, json.JSONDecodeError):
        return default
    return payload if isinstance(payload, dict) else default


def validate_slug(value: str, *, pattern, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not pattern.match(normalized):
        raise AgentsValidationError(f"Invalid {field_name}: {normalized}")
    return normalized


def validate_role_id(role_id: str) -> str:
    return validate_slug(role_id, pattern=ROLE_ID_PATTERN, field_name="role_id")


def validate_agent_type_id(agent_type_id: str) -> str:
    return validate_slug(agent_type_id, pattern=AGENT_TYPE_ID_PATTERN, field_name="agent_type_id")


def role_file_path(data_root: Path, role_id: str) -> Path:
    normalized = validate_role_id(role_id)
    root = roles_root(data_root).resolve()
    path = (root / normalized / "ROLE.md").resolve()
    if root not in path.parents:
        raise AgentsValidationError("Role path escaped agents data root.")
    return path


def parse_role_markdown(raw: str, *, role_id: str) -> dict:
    if not raw.startswith("---\n"):
        raise AgentsValidationError(f"Role `{role_id}` is missing frontmatter.")
    try:
        _prefix, remainder = raw.split("---\n", 1)
        header, body = remainder.split("\n---\n", 1)
    except ValueError as error:
        raise AgentsValidationError(f"Role `{role_id}` has invalid frontmatter.") from error
    metadata: dict[str, str] = {}
    for line in header.splitlines():
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        metadata[key.strip()] = value.strip()
    name = metadata.get("name") or role_id
    description = metadata.get("description") or ""
    instructions = body.strip()
    if not instructions:
        raise AgentsValidationError(f"Role `{role_id}` has empty instructions.")
    return {"id": role_id, "name": name, "description": description, "instructions": instructions}


def role_markdown(role: dict) -> str:
    role_id = validate_role_id(str(role.get("id") or ""))
    name = " ".join(str(role.get("name") or role_id).split()).strip()
    description = " ".join(str(role.get("description") or "").split()).strip()
    instructions = str(role.get("instructions") or "").strip()
    if not instructions:
        raise AgentsValidationError("Role instructions are required.")
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{instructions}\n"


def list_roles(data_root: Path) -> list[dict]:
    ensure_data_root(data_root)
    roles: list[dict] = []
    for role_dir in sorted(path for path in roles_root(data_root).iterdir() if path.is_dir()):
        role_id = validate_role_id(role_dir.name)
        role_path = role_dir / "ROLE.md"
        if role_path.is_file():
            roles.append(parse_role_markdown(role_path.read_text(encoding="utf-8"), role_id=role_id))
    return roles


def get_role(data_root: Path, role_id: str) -> dict | None:
    path = role_file_path(data_root, role_id)
    if not path.is_file():
        return None
    return parse_role_markdown(path.read_text(encoding="utf-8"), role_id=validate_role_id(role_id))


def save_role(data_root: Path, role: dict) -> dict:
    role_id = validate_role_id(str(role.get("id") or ""))
    path = role_file_path(data_root, role_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(role_markdown({"id": role_id, **role}), encoding="utf-8")
    saved = get_role(data_root, role_id)
    if saved is None:
        raise AgentsValidationError(f"Role `{role_id}` was not saved.")
    return saved


def delete_role(data_root: Path, role_id: str) -> bool:
    normalized = validate_role_id(role_id)
    if any(agent_type.get("role_id") == normalized for agent_type in list_agent_types(data_root)):
        raise AgentsValidationError(f"Role `{normalized}` is still referenced by an agent type.")
    path = role_file_path(data_root, normalized)
    if not path.is_file():
        return False
    path.unlink()
    try:
        path.parent.rmdir()
    except OSError:
        pass
    return True


def list_agent_types(data_root: Path) -> list[dict]:
    ensure_data_root(data_root)
    payload = read_json(agent_types_path(data_root), {"schema_version": "1", "agent_types": []})
    return [normalize_agent_type(item) for item in payload.get("agent_types", []) if isinstance(item, dict)]


def write_agent_types(data_root: Path, agent_types: list[dict]) -> None:
    write_json(agent_types_path(data_root), {"schema_version": "1", "agent_types": agent_types})


def normalize_agent_type(payload: dict) -> dict:
    agent_type_id = validate_agent_type_id(str(payload.get("id") or ""))
    role_id = validate_role_id(str(payload.get("role_id") or ""))
    trace = str(payload.get("trace_verbosity") or "compact")
    if trace not in TRACE_VERBOSITIES:
        raise AgentsValidationError(f"Invalid trace_verbosity: {trace}")
    skills = payload.get("skill_ids") if isinstance(payload.get("skill_ids"), list) else payload.get("codex_skill_ids")
    if not isinstance(skills, list):
        skills = []
    return {
        "id": agent_type_id,
        "name": " ".join(str(payload.get("name") or agent_type_id).split()).strip(),
        "description": " ".join(str(payload.get("description") or "").split()).strip(),
        "role_id": role_id,
        "skill_ids": [str(skill_id).strip() for skill_id in skills if str(skill_id).strip()],
        "trace_verbosity": trace,
        "enabled": bool(payload.get("enabled", True)),
        "created_at": str(payload.get("created_at") or now_timestamp()),
        "updated_at": str(payload.get("updated_at") or now_timestamp()),
    }


def get_agent_type(data_root: Path, agent_type_id: str) -> dict | None:
    normalized = validate_agent_type_id(agent_type_id)
    return next((item for item in list_agent_types(data_root) if item["id"] == normalized), None)


def save_agent_type(data_root: Path, payload: dict) -> dict:
    timestamp = now_timestamp()
    existing = get_agent_type(data_root, str(payload.get("id") or ""))
    candidate = normalize_agent_type(
        {
            **(existing or {}),
            **payload,
            "created_at": (existing or {}).get("created_at") or timestamp,
            "updated_at": timestamp,
        }
    )
    if get_role(data_root, candidate["role_id"]) is None:
        raise AgentsValidationError(f"Unknown role id: {candidate['role_id']}")
    agent_types = [item for item in list_agent_types(data_root) if item["id"] != candidate["id"]]
    agent_types.append(candidate)
    write_agent_types(data_root, sorted(agent_types, key=lambda item: item["name"].casefold()))
    return candidate


def delete_agent_type(data_root: Path, agent_type_id: str) -> bool:
    normalized = validate_agent_type_id(agent_type_id)
    original = list_agent_types(data_root)
    remaining = [item for item in original if item["id"] != normalized]
    write_agent_types(data_root, remaining)
    return len(remaining) != len(original)


def read_common_prompt(data_root: Path) -> str:
    ensure_data_root(data_root)
    return common_prompt_path(data_root).read_text(encoding="utf-8")


def write_common_prompt(data_root: Path, prompt: str) -> str:
    ensure_data_root(data_root)
    normalized = str(prompt or "").strip() + "\n"
    common_prompt_path(data_root).write_text(normalized, encoding="utf-8")
    return normalized
