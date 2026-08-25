"""Bounded agent skill-capability entries for orchestration prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.inter_agent.models import AgentParticipantSnapshot
from core.skills.service import list_available_workspace_skills


MAX_SKILL_CAPABILITY_CHARS = 2048


def enabled_workspace_skill_ids(
    *,
    workspace_id: str,
    start_path: Path,
    app_id: str,
) -> list[str]:
    """List enabled ids without making optional prompt enrichment fatal."""
    try:
        skills = list_available_workspace_skills(
            workspace_id=workspace_id,
            start_path=start_path,
            app_id=app_id,
        )
    except (OSError, ValueError):
        return []
    return [skill.skill_id for skill in skills]


def requires_open_explicit_catalog(
    root_snapshot: AgentParticipantSnapshot,
    items: list[dict[str, Any]],
) -> bool:
    """Return whether any prompt entry needs the workspace-wide skill ids."""
    if root_snapshot.skill_activation_mode == "explicit" and not root_snapshot.skill_ids:
        return True
    return any(
        str(item.get("skill_activation_mode") or "implicit").strip() == "explicit"
        and not _string_items(item.get("skill_ids"))
        for item in items
    )


def catalog_prompt_entry(item: dict[str, Any], *, default_skill_ids: list[str] | None = None) -> str:
    """Describe one compact specialist without exposing prompt content."""
    identifier = str(item.get("id") or "").strip()
    name = " ".join(str(item.get("name") or identifier).split())
    description = " ".join(str(item.get("description") or "").split())[:240]
    entry = f"{identifier}: {name}" + (f" — {description}" if description else "")
    return _with_skill_capability(
        entry,
        mode=str(item.get("skill_activation_mode") or "implicit"),
        skill_ids=_string_items(item.get("skill_ids")),
        default_skill_ids=default_skill_ids,
    )


def root_prompt_entry(
    snapshot: AgentParticipantSnapshot,
    *,
    default_skill_ids: list[str] | None = None,
) -> str:
    """Describe the default worker and its server-owned skill capability."""
    entry = f"default (omit agent_type_id): {snapshot.agent_type_id}: {snapshot.label}"
    return _with_skill_capability(
        entry,
        mode=snapshot.skill_activation_mode,
        skill_ids=snapshot.skill_ids,
        default_skill_ids=default_skill_ids,
    )


def _with_skill_capability(
    entry: str,
    *,
    mode: str,
    skill_ids: list[str],
    default_skill_ids: list[str] | None,
) -> str:
    mode = str(mode or "implicit").strip()
    if mode not in {"implicit", "explicit"}:
        mode = "implicit"
    effective_skill_ids = skill_ids
    if mode == "explicit" and not effective_skill_ids:
        effective_skill_ids = list(default_skill_ids or [])
    normalized_skill_ids, omitted_count = _bounded_skill_ids(effective_skill_ids)
    skill_id_label = ",".join(normalized_skill_ids)
    if omitted_count:
        separator = "," if skill_id_label else ""
        skill_id_label += f"{separator}…(+{omitted_count} more)"
    if mode == "explicit":
        allowed = skill_id_label or "any enabled workspace skill"
        return f"{entry} [skill mode=explicit; allowed skill ids={allowed}]"
    assigned = skill_id_label or "workspace default catalog"
    return f"{entry} [skill mode=implicit; assigned skill ids={assigned}]"


def _bounded_skill_ids(skill_ids: list[str]) -> tuple[list[str], int]:
    normalized = sorted({str(item).strip()[:160] for item in skill_ids if str(item).strip()})
    displayed: list[str] = []
    character_count = 0
    for skill_id in normalized:
        next_count = character_count + len(skill_id) + (1 if displayed else 0)
        if next_count > MAX_SKILL_CAPABILITY_CHARS:
            break
        displayed.append(skill_id)
        character_count = next_count
    return displayed, len(normalized) - len(displayed)


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [text for item in value if (text := str(item or "").strip())]
