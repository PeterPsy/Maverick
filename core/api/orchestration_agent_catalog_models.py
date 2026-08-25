"""Revision-bound catalog records shared by orchestration decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.models import AgentParticipantSnapshot
from core.inter_agent.orchestration_planner_catalog import OrchestrationPlannerCatalog


@dataclass
class OrchestrationAgentCatalog:
    root_snapshot: AgentParticipantSnapshot
    planner_catalog: OrchestrationPlannerCatalog
    provider_app_id: str | None
    snapshots: dict[str, AgentParticipantSnapshot]
    revision_id: str

    @property
    def available_agent_type_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.snapshots))

    def resolve(self, agent_type_id: str) -> AgentParticipantSnapshot:
        normalized = str(agent_type_id or "").strip()
        snapshot = self.snapshots.get(normalized)
        if snapshot is None:
            raise InterAgentValidationError(
                f"Agent type `{normalized}` is not available in catalog revision `{self.revision_id}`."
            )
        return snapshot


@dataclass
class OrchestrationAgentCatalogSource:
    """Refreshable context and revision cache for one orchestration worker."""

    root_snapshot: AgentParticipantSnapshot
    provider_app_id: str | None
    state: Any
    workspace_id: str
    user: Any
    root_system_prompt: str
    start_path: Path
    cache: dict[tuple[str, str], AgentParticipantSnapshot] = field(default_factory=dict)

    def refresh(self) -> OrchestrationAgentCatalog:
        from core.api.orchestration_agent_catalog_materialization import (
            refresh_orchestration_agent_catalog,
        )

        return refresh_orchestration_agent_catalog(self)


@dataclass(frozen=True)
class CompactAgentCatalogView:
    items: tuple[dict[str, Any], ...]
    signature: str


class CatalogRevisionChanged(RuntimeError):
    """Internal retry signal for a provider catalog changed during one read."""
