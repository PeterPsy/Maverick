"""Shared resume dispatch for inter-agent operator surfaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.service import InterAgentService


OrchestrationResume = Callable[..., Any]


def resume_run_from_surface(
    service: InterAgentService,
    state: Any,
    run: Any,
    *,
    reason: str,
    orchestration_resume: OrchestrationResume | None,
) -> Any:
    """Resume through the hosted scheduler owner when the run is orchestrated."""
    if run.mode != "orchestrated":
        return service.resume_run(
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            reason=reason,
        )
    if orchestration_resume is None:
        raise InterAgentOperationError("Orchestrated runs must be resumed through the hosted core scheduler.")
    return orchestration_resume(
        state,
        service,
        workspace_id=run.workspace_id,
        run_id=run.run_id,
        reason=reason,
    )
