"""Globally bounded and pageable catalog text for orchestration planners."""

from __future__ import annotations

from dataclasses import dataclass
import re

from core.inter_agent.errors import InterAgentValidationError


MAX_PLANNER_CATALOG_PAGE_CHARS = 8192
_SECTION_CONTENT_CHARS = 3500
_AGENT_CURSOR_RE = re.compile(r"^agents:(\d+)$")
_SKILL_CURSOR_RE = re.compile(r"^skills:(s\d+):(\d+)$")


@dataclass(frozen=True)
class PlannerCatalogPage:
    """One prompt-safe catalog page and its validated continuation cursors."""

    text: str
    next_cursors: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannerSkillScope:
    token: str
    label: str
    skill_ids: tuple[str, ...]


@dataclass(frozen=True)
class PlannerAgentEntry:
    text: str
    skill_scope_token: str | None = None


@dataclass(frozen=True)
class OrchestrationPlannerCatalog:
    """Server-owned catalog with a global per-prompt budget and opaque paging."""

    agent_entries: tuple[PlannerAgentEntry, ...]
    skill_scopes: tuple[PlannerSkillScope, ...] = ()

    @classmethod
    def from_text_entries(cls, entries: tuple[str, ...]) -> OrchestrationPlannerCatalog:
        return cls(
            tuple(
                PlannerAgentEntry(text[:512])
                for entry in entries
                if (text := " ".join(str(entry).split()))
            )
        )

    def initial_page(self) -> PlannerCatalogPage:
        agent_page = self.index_page()
        parts = [agent_page.text]
        cursors = list(agent_page.next_cursors)
        first_scope = next(
            (
                scope
                for scope in self.skill_scopes
                if f"skills:{scope.token}:0" in cursors
            ),
            self.skill_scopes[0] if self.skill_scopes else None,
        )
        if first_scope is not None:
            first_cursor = f"skills:{first_scope.token}:0"
            skill_page = self._skill_page(first_scope, 0)
            parts.append(skill_page.text)
            cursors = [cursor for cursor in cursors if cursor != first_cursor]
            cursors.extend(skill_page.next_cursors)
        page = PlannerCatalogPage(
            text="\n\n".join(part for part in parts if part),
            next_cursors=_unique(cursors),
        )
        _assert_page_budget(page)
        return page

    def index_page(self) -> PlannerCatalogPage:
        """Return the bounded agent index without resending workspace skill IDs."""
        return self._agent_page(0)

    def page(self, cursor: str) -> PlannerCatalogPage:
        normalized = str(cursor or "").strip()
        agent_match = _AGENT_CURSOR_RE.fullmatch(normalized)
        if agent_match:
            return self._agent_page(int(agent_match.group(1)))
        skill_match = _SKILL_CURSOR_RE.fullmatch(normalized)
        if skill_match:
            token, raw_offset = skill_match.groups()
            scope = next((item for item in self.skill_scopes if item.token == token), None)
            if scope is None:
                raise InterAgentValidationError("Unknown planner skill-catalog cursor.")
            return self._skill_page(scope, int(raw_offset))
        raise InterAgentValidationError("Invalid planner catalog cursor.")

    def _agent_page(self, offset: int) -> PlannerCatalogPage:
        if offset < 0 or (offset >= len(self.agent_entries) and (offset or self.agent_entries)):
            raise InterAgentValidationError("Planner agent-catalog cursor is out of range.")
        lines: list[str] = []
        content_chars = 0
        index = offset
        visible_scope_cursors: list[str] = []
        while index < len(self.agent_entries):
            entry = self.agent_entries[index]
            line = f"- {entry.text}"
            next_chars = content_chars + len(line) + (1 if lines else 0)
            if lines and next_chars > _SECTION_CONTENT_CHARS:
                break
            lines.append(line)
            content_chars = next_chars
            if entry.skill_scope_token:
                visible_scope_cursors.append(f"skills:{entry.skill_scope_token}:0")
            index += 1
        if not lines:
            lines.append("- default orchestrator capability")
        cursors = visible_scope_cursors
        footer: list[str] = []
        if index < len(self.agent_entries):
            cursor = f"agents:{index}"
            cursors.append(cursor)
            footer.append(f"More agent types are available with catalog cursor `{cursor}`.")
        footer.append(
            "To inspect another page before deciding, return only "
            '{"catalog_lookup":{"cursor":"<cursor>"}}.'
        )
        page = PlannerCatalogPage(
            text="\n".join(("Available agent types (server-authoritative capability page):", *lines, *footer)),
            next_cursors=_unique(cursors),
        )
        _assert_page_budget(page)
        return page

    def _skill_page(self, scope: PlannerSkillScope, offset: int) -> PlannerCatalogPage:
        if offset < 0 or offset >= len(scope.skill_ids):
            raise InterAgentValidationError("Planner skill-catalog cursor is out of range.")
        displayed: list[str] = []
        content_chars = 0
        index = offset
        while index < len(scope.skill_ids):
            skill_id = scope.skill_ids[index]
            next_chars = content_chars + len(skill_id) + (2 if displayed else 0)
            if displayed and next_chars > _SECTION_CONTENT_CHARS:
                break
            displayed.append(skill_id)
            content_chars = next_chars
            index += 1
        lines = [
            f"Enabled skill IDs for scope `{scope.token}` ({scope.label}); "
            f"items {offset + 1}-{index} of {len(scope.skill_ids)}:",
            ", ".join(displayed),
        ]
        cursors: list[str] = []
        if index < len(scope.skill_ids):
            cursor = f"skills:{scope.token}:{index}"
            cursors.append(cursor)
            lines.append(f"Next skill page cursor: `{cursor}`.")
        lines.append(
            "Use only IDs shown on retrieved pages. To inspect another page, return only "
            '{"catalog_lookup":{"cursor":"<cursor>"}}.'
        )
        page = PlannerCatalogPage(text="\n".join(lines), next_cursors=tuple(cursors))
        _assert_page_budget(page)
        return page


def _assert_page_budget(page: PlannerCatalogPage) -> None:
    if len(page.text) > MAX_PLANNER_CATALOG_PAGE_CHARS:
        raise RuntimeError("Planner catalog page exceeded its global prompt budget.")


def _unique(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))
