"""Transient planner catalog lookups before durable orchestration decisions."""

from __future__ import annotations

from typing import Any

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.orchestration_plan import parse_catalog_lookup_request
from core.inter_agent.orchestration_planner_catalog import (
    OrchestrationPlannerCatalog,
    PlannerCatalogPage,
)
from core.inter_agent.orchestration_prompts import catalog_lookup_followup_prompt
from core.inter_agent.orchestration_runtime import ParticipantTurnExecutor


MAX_CATALOG_LOOKUP_ROUNDS_PER_DECISION = 2


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
    advertised_skill_scopes = set(
        initial_catalog_page.skill_scope_tokens if initial_catalog_page is not None else ()
    )
    requested_lookups: set[Any] = set()
    lookup_index = 0
    while True:
        request = parse_catalog_lookup_request(output)
        if request is None:
            return output
        if planner_catalog is None:
            raise InterAgentValidationError("Planner requested a catalog lookup when no catalog is available.")
        if lookup_index >= MAX_CATALOG_LOOKUP_ROUNDS_PER_DECISION:
            raise InterAgentValidationError("Planner exceeded the bounded catalog lookup budget for one decision.")
        if any(cursor not in advertised_cursors for cursor in request.cursors):
            raise InterAgentValidationError("Planner requested a catalog cursor that was not advertised.")
        if request.skill_scope is not None and request.skill_scope not in advertised_skill_scopes:
            raise InterAgentValidationError("Planner requested a skill scope that was not advertised.")
        if request in requested_lookups:
            raise InterAgentValidationError("Planner repeated a catalog lookup request.")
        requested_lookups.add(request)
        lookup_index += 1
        page = planner_catalog.lookup(request)
        advertised_cursors.update(page.next_cursors)
        advertised_skill_scopes.update(page.skill_scope_tokens)
        output = execute_turn(
            orchestrator,
            catalog_lookup_followup_prompt(decision_kind=decision_kind, catalog_page=page.text),
            f"{client_message_id}:catalog:{lookup_index}",
            (),
        )
