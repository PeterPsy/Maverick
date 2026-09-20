"""Resolve and prepare the skill boundary for one runtime launch."""

from __future__ import annotations

import time

from core.providers.service import prepare_runtime_skills
from core.runtime.research_runtime import runtime_session_is_research
from core.skills.service import resolve_available_runtime_skills


def resolve_and_prepare_runtime_skills(
    state,
    *,
    session,
    runtime_adapter,
) -> tuple[list, float, float]:
    resolve_started_at = time.perf_counter()
    research = runtime_session_is_research(session)
    if research:
        skills = []
    else:
        skills = resolve_available_runtime_skills(
            session, start_path=state.repository_root,
        )
    resolve_ms = (time.perf_counter() - resolve_started_at) * 1000
    prepare_ms = 0.0
    if runtime_adapter is not None and not research and (
        skills or bool(getattr(runtime_adapter, "synchronizes_runtime_skills", False))
    ):
        prepare_started_at = time.perf_counter()
        prepare_runtime_skills(
            state.provider_store,
            session=session,
            skills=skills,
            runtime_adapter=runtime_adapter,
        )
        prepare_ms = (time.perf_counter() - prepare_started_at) * 1000
    return skills, resolve_ms, prepare_ms
