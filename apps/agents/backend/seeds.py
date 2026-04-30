"""Seed helpers for the native agents app."""

from __future__ import annotations

from pathlib import Path

from store import ensure_data_root, list_agent_types, list_roles, parse_role_markdown, save_agent_type, save_role


SOURCE_ROLES_ROOT = Path(__file__).resolve().parents[1] / "roles"


def source_role_seeds(source_roles_root: Path = SOURCE_ROLES_ROOT) -> list[dict]:
    roles: list[dict] = []
    for role_dir in sorted(path for path in source_roles_root.iterdir() if path.is_dir()):
        role_file = role_dir / "ROLE.md"
        if role_file.is_file():
            roles.append(parse_role_markdown(role_file.read_text(encoding="utf-8"), role_id=role_dir.name))
    return roles


def seed_defaults(data_root: Path) -> dict:
    ensure_data_root(data_root)
    role_seeds = source_role_seeds()
    if not list_roles(data_root):
        for role in role_seeds:
            save_role(data_root, role)
    if not list_agent_types(data_root):
        for role in role_seeds:
            role_id = role["id"]
            save_agent_type(
                data_root,
                {
                    "id": f"agent-type-{role_id}",
                    "name": role["name"],
                    "description": role["description"],
                    "role_id": role_id,
                    "skill_ids": [],
                    "trace_verbosity": "verbose" if role_id in {"server-coding-engineer", "code-review-auditor", "agent-builder"} else "compact",
                    "enabled": True,
                },
            )
    return {
        "role_count": len(list_roles(data_root)),
        "agent_type_count": len(list_agent_types(data_root)),
    }
