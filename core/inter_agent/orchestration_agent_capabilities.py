"""Enabled skill capabilities for the dynamic orchestration planner."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.inter_agent.models import AgentParticipantSnapshot
from core.inter_agent.orchestration_planner_catalog import (
    OrchestrationPlannerCatalog,
    PlannerAgentEntry,
    PlannerSkillScope,
)
from core.skills.service import list_available_workspace_skills


CATALOG_AVAILABLE = "available"
CATALOG_UNAVAILABLE = "unavailable"
_CATALOG_STATES = frozenset({CATALOG_AVAILABLE, CATALOG_UNAVAILABLE})


@dataclass(frozen=True)
class EnabledWorkspaceSkillCatalog:
    """One authoritative enumeration attempt, including its availability state."""

    state: str
    skill_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.state not in _CATALOG_STATES:
            raise ValueError(f"Unsupported workspace skill catalog state `{self.state}`.")
        normalized = tuple(sorted({text for item in self.skill_ids if (text := str(item or "").strip())}))
        if self.state == CATALOG_UNAVAILABLE:
            normalized = ()
        object.__setattr__(self, "skill_ids", normalized)


def enabled_workspace_skill_catalog(
    *,
    workspace_id: str,
    start_path: Path,
    app_id: str,
) -> EnabledWorkspaceSkillCatalog:
    """Enumerate enabled skills while preserving empty versus unavailable."""
    try:
        skills = list_available_workspace_skills(
            workspace_id=workspace_id,
            start_path=start_path,
            app_id=app_id,
        )
        skill_ids = tuple(skill.skill_id for skill in skills)
    except Exception:
        return EnabledWorkspaceSkillCatalog(state=CATALOG_UNAVAILABLE, skill_ids=())
    return EnabledWorkspaceSkillCatalog(state=CATALOG_AVAILABLE, skill_ids=skill_ids)


def requires_explicit_catalog(
    root_snapshot: AgentParticipantSnapshot,
    items: list[dict[str, Any]],
) -> bool:
    if root_snapshot.skill_activation_mode == "explicit":
        return True
    return any(
        str(item.get("skill_activation_mode") or "implicit").strip() == "explicit"
        for item in items
    )


def build_orchestration_planner_catalog(
    root_snapshot: AgentParticipantSnapshot,
    items: list[dict[str, Any]],
    *,
    enabled_skills: EnabledWorkspaceSkillCatalog,
) -> OrchestrationPlannerCatalog:
    scopes: list[PlannerSkillScope] = []
    scope_tokens: dict[tuple[str, ...], str] = {}

    def register_scope(skill_ids: tuple[str, ...], *, label: str) -> str:
        token = scope_tokens.get(skill_ids)
        if token is not None:
            return token
        token = f"s{len(scopes)}"
        scope_tokens[skill_ids] = token
        scopes.append(PlannerSkillScope(token=token, label=label, skill_ids=skill_ids))
        return token

    root_agent_type_id = str(root_snapshot.agent_type_id or "generalist").strip()[:128]
    root_label = " ".join(str(root_snapshot.label or root_agent_type_id).split())[:160]
    entries = [
        _agent_entry(
            f"default (omit agent_type_id): {root_agent_type_id}: {root_label}",
            mode=root_snapshot.skill_activation_mode,
            assigned_skill_ids=root_snapshot.skill_ids,
            enabled_skills=enabled_skills,
            register_scope=register_scope,
        )
    ]
    for item in items:
        identifier = str(item.get("id") or "").strip()
        if not identifier or identifier == root_snapshot.agent_type_id:
            continue
        name = " ".join(str(item.get("name") or identifier).split())[:160]
        description = " ".join(str(item.get("description") or "").split())[:240]
        label = f"{identifier}: {name}" + (f" — {description}" if description else "")
        entries.append(
            _agent_entry(
                label,
                mode=str(item.get("skill_activation_mode") or "implicit"),
                assigned_skill_ids=_string_items(item.get("skill_ids")),
                enabled_skills=enabled_skills,
                register_scope=register_scope,
            )
        )
    return OrchestrationPlannerCatalog(agent_entries=tuple(entries), skill_scopes=tuple(scopes))


def _agent_entry(
    label: str,
    *,
    mode: str,
    assigned_skill_ids: list[str],
    enabled_skills: EnabledWorkspaceSkillCatalog,
    register_scope: Any,
) -> PlannerAgentEntry:
    if str(mode or "implicit").strip() != "explicit":
        return PlannerAgentEntry(
            f"{label} [skill mode=implicit; skills are runtime-managed; omit invoked_skill_ids]"
        )
    if enabled_skills.state == CATALOG_UNAVAILABLE:
        return PlannerAgentEntry(
            f"{label} [skill mode=explicit; catalog unavailable; do not select invoked_skill_ids]"
        )
    enabled_ids = set(enabled_skills.skill_ids)
    assigned = set(_string_items(assigned_skill_ids))
    effective = tuple(sorted(enabled_ids if not assigned else enabled_ids.intersection(assigned)))
    if not effective:
        return PlannerAgentEntry(
            f"{label} [skill mode=explicit; none available; invoked_skill_ids must be empty]"
        )
    scope_token = register_scope(effective, label="shared enabled workspace catalog" if not assigned else label)
    return PlannerAgentEntry(
        f"{label} [skill mode=explicit; invocable skill scope={scope_token}; enabled count={len(effective)}; "
        f"catalog cursor=skills:{scope_token}:0]",
        skill_scope_token=scope_token,
    )


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [text for item in value if (text := str(item or "").strip())]
