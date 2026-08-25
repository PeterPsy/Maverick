"""Decision-scoped planner catalog and participant resolver binding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from core.inter_agent.orchestration_participants import AgentSnapshotResolver
from core.inter_agent.orchestration_planner_catalog import OrchestrationPlannerCatalog


class OrchestrationCatalogSnapshot(Protocol):
    planner_catalog: OrchestrationPlannerCatalog
    available_agent_type_ids: tuple[str, ...]

    def resolve(self, agent_type_id: str) -> Any: ...


OrchestrationCatalogSnapshotProvider = Callable[[], OrchestrationCatalogSnapshot]


@dataclass(frozen=True)
class DecisionCatalogMaterial:
    planner_catalog: OrchestrationPlannerCatalog
    available_agent_type_ids: tuple[str, ...]
    snapshot_resolver: AgentSnapshotResolver | None


def decision_catalog_material(
    provider: OrchestrationCatalogSnapshotProvider | None,
    *,
    planner_catalog: OrchestrationPlannerCatalog,
    available_agent_type_ids: tuple[str, ...],
    snapshot_resolver: AgentSnapshotResolver | None,
) -> DecisionCatalogMaterial:
    if provider is None:
        return DecisionCatalogMaterial(
            planner_catalog=planner_catalog,
            available_agent_type_ids=available_agent_type_ids,
            snapshot_resolver=snapshot_resolver,
        )
    catalog = provider()
    return DecisionCatalogMaterial(
        planner_catalog=catalog.planner_catalog,
        available_agent_type_ids=catalog.available_agent_type_ids,
        snapshot_resolver=catalog.resolve,
    )


def lazy_catalog_resolver(
    provider: OrchestrationCatalogSnapshotProvider | None,
) -> AgentSnapshotResolver | None:
    if provider is None:
        return None
    cached: OrchestrationCatalogSnapshot | None = None

    def resolve(agent_type_id: str) -> Any:
        nonlocal cached
        if cached is None:
            cached = provider()
        return cached.resolve(agent_type_id)

    return resolve
