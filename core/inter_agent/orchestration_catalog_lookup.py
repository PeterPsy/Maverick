"""Transient planner catalog lookups before durable orchestration decisions."""

from __future__ import annotations

from typing import Any

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.orchestration_plan import parse_catalog_lookup_cursor
from core.inter_agent.orchestration_planner_catalog import (
    OrchestrationPlannerCatalog,
    PlannerCatalogPage,
)
from core.inter_agent.orchestration_prompts import catalog_lookup_followup_prompt
from core.inter_agent.orchestration_runtime import ParticipantTurnExecutor


def execute_catalog_aware_planner_turn(
    execute_turn: ParticipantTurnExecutor,
    orchestrator: Any,
    prompt: str,
    client_message_id: str,
    *,
    decision_kind: str,
    planner_catalog: OrchestrationPlannerCatalog | None,
    initial_catalog_page: PlannerCatalogPage | None,
) -> str:
    """Resolve validated lookup-only turns, then return the durable decision output."""
    output = execute_turn(orchestrator, prompt, client_message_id, ())
    advertised_cursors = set(initial_catalog_page.next_cursors if initial_catalog_page is not None else ())
    requested_cursors: set[str] = set()
    lookup_index = 0
    while True:
        cursor = parse_catalog_lookup_cursor(output)
        if cursor is None:
            return output
        if planner_catalog is None:
            raise InterAgentValidationError("Planner requested a catalog lookup when no catalog is available.")
        if cursor not in advertised_cursors:
            raise InterAgentValidationError("Planner requested a catalog cursor that was not advertised.")
        if cursor in requested_cursors:
            raise InterAgentValidationError("Planner repeated a catalog lookup cursor.")
        requested_cursors.add(cursor)
        lookup_index += 1
        page = planner_catalog.page(cursor)
        advertised_cursors.update(page.next_cursors)
        output = execute_turn(
            orchestrator,
            catalog_lookup_followup_prompt(decision_kind=decision_kind, catalog_page=page.text),
            f"{client_message_id}:catalog:{lookup_index}",
            (),
        )
