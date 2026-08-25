"""Bounded cursor batches and direct searches over a planner catalog."""

from __future__ import annotations

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.orchestration_planner_catalog import (
    MAX_CATALOG_LOOKUP_CURSORS,
    MAX_CATALOG_SEARCH_RESULTS,
    OrchestrationPlannerCatalog,
    PlannerAgentEntry,
    PlannerCatalogLookupRequest,
    PlannerCatalogPage,
    _assert_page_budget,
    _lookup_instruction,
    _SECTION_CONTENT_CHARS,
    _unique,
)


def lookup_planner_catalog(
    catalog: OrchestrationPlannerCatalog,
    request: PlannerCatalogLookupRequest,
) -> PlannerCatalogPage:
    if request.cursors:
        return _cursor_batch(catalog, request.cursors)
    if request.agent_prefix is not None:
        return _agent_search(catalog, request.agent_prefix)
    if request.skill_scope is not None:
        return _skill_search(
            catalog,
            request.skill_scope,
            prefix=request.skill_prefix,
            exact_ids=request.skill_ids,
        )
    raise InterAgentValidationError("Planner catalog lookup has no selector.")


def _cursor_batch(
    catalog: OrchestrationPlannerCatalog,
    cursors: tuple[str, ...],
) -> PlannerCatalogPage:
    if not cursors or len(cursors) > MAX_CATALOG_LOOKUP_CURSORS:
        raise InterAgentValidationError(
            f"Planner catalog lookup accepts 1-{MAX_CATALOG_LOOKUP_CURSORS} cursors."
        )
    pages = [catalog.page(cursor) for cursor in cursors]
    combined = PlannerCatalogPage(
        text="\n\n".join(page.text for page in pages),
        next_cursors=_unique([cursor for page in pages for cursor in page.next_cursors]),
        skill_scope_tokens=_unique(
            [token for page in pages for token in page.skill_scope_tokens]
        ),
    )
    _assert_page_budget(combined)
    return combined


def _agent_search(
    catalog: OrchestrationPlannerCatalog,
    prefix: str,
) -> PlannerCatalogPage:
    query = " ".join(str(prefix or "").split()).casefold()
    if not query:
        raise InterAgentValidationError("Planner agent catalog search prefix is empty.")
    matches = [entry for entry in catalog.agent_entries if query in entry.text.casefold()]
    lines: list[str] = []
    cursors: list[str] = []
    shown_entries: list[PlannerAgentEntry] = []
    content_chars = 0
    for entry in matches[:MAX_CATALOG_SEARCH_RESULTS]:
        line = f"- {entry.text}"
        if lines and content_chars + len(line) + 1 > _SECTION_CONTENT_CHARS:
            break
        lines.append(line)
        shown_entries.append(entry)
        content_chars += len(line) + (1 if lines else 0)
        if entry.skill_scope_token:
            cursors.append(f"skills:{entry.skill_scope_token}:0")
    if not lines:
        lines.append("- no matching agent type")
    if len(matches) > len(shown_entries):
        lines.append(f"More matches exist; refine the prefix ({len(matches)} total).")
    lines.append(_lookup_instruction())
    page = PlannerCatalogPage(
        text="\n".join((f"Agent catalog search for `{prefix}`:", *lines)),
        next_cursors=_unique(cursors),
        skill_scope_tokens=_unique(
            [entry.skill_scope_token for entry in shown_entries if entry.skill_scope_token]
        ),
    )
    _assert_page_budget(page)
    return page

def _skill_search(
    catalog: OrchestrationPlannerCatalog,
    token: str,
    *,
    prefix: str | None,
    exact_ids: tuple[str, ...],
) -> PlannerCatalogPage:
    scope = next((item for item in catalog.skill_scopes if item.token == token), None)
    if scope is None:
        raise InterAgentValidationError("Unknown planner skill-catalog scope.")
    normalized_prefix = str(prefix or "").strip().casefold()
    requested_ids = tuple(
        dict.fromkeys(
            str(item or "").strip()
            for item in exact_ids
            if str(item or "").strip()
        )
    )
    if not normalized_prefix and not requested_ids:
        raise InterAgentValidationError("Planner skill search requires a prefix or exact IDs.")
    available = set(scope.skill_ids)
    matches = [skill_id for skill_id in requested_ids if skill_id in available]
    if normalized_prefix:
        matches.extend(
            skill_id
            for skill_id in scope.skill_ids
            if skill_id.casefold().startswith(normalized_prefix)
        )
    matches = list(dict.fromkeys(matches))
    displayed: list[str] = []
    content_chars = 0
    for skill_id in matches[:MAX_CATALOG_SEARCH_RESULTS]:
        next_chars = content_chars + len(skill_id) + (2 if displayed else 0)
        if displayed and next_chars > _SECTION_CONTENT_CHARS:
            break
        displayed.append(skill_id)
        content_chars = next_chars
    lines = [
        f"Skill catalog search in scope `{scope.token}` ({scope.label}); {len(matches)} match(es):",
        ", ".join(displayed) if displayed else "none",
    ]
    missing = [skill_id for skill_id in requested_ids if skill_id not in available]
    if missing:
        lines.append(f"Unknown requested IDs: {', '.join(missing[:32])}.")
    if len(matches) > len(displayed):
        lines.append(f"More matches exist; refine the prefix ({len(matches)} total).")
    lines.append(_lookup_instruction())
    page = PlannerCatalogPage(text="\n".join(lines), skill_scope_tokens=(scope.token,))
    _assert_page_budget(page)
    return page
