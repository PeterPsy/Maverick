from __future__ import annotations

import re
from pathlib import Path
import unittest
from unittest.mock import patch

from core.inter_agent.models import AgentParticipantSnapshot
from core.inter_agent.orchestration_agent_capabilities import (
    CATALOG_AVAILABLE,
    CATALOG_UNAVAILABLE,
    EnabledWorkspaceSkillCatalog,
    build_orchestration_planner_catalog,
    enabled_workspace_skill_catalog,
)
from core.inter_agent.orchestration_planner_catalog import MAX_PLANNER_CATALOG_PAGE_CHARS


def _root(*, skill_ids: list[str] | None = None) -> AgentParticipantSnapshot:
    return AgentParticipantSnapshot(
        agent_type_id="generalist",
        label="Generalist",
        system_prompt="Work carefully.",
        skill_ids=list(skill_ids or []),
        skill_catalog_app_id="skills",
        skill_activation_mode="explicit",
    )


class OrchestrationAgentCapabilitiesTest(unittest.TestCase):
    def test_enumeration_preserves_empty_versus_unavailable(self) -> None:
        with patch(
            "core.inter_agent.orchestration_agent_capabilities.list_available_workspace_skills",
            return_value=[],
        ):
            empty = enabled_workspace_skill_catalog(
                workspace_id="default",
                start_path=Path("/tmp/repo"),
                app_id="skills",
            )
        with patch(
            "core.inter_agent.orchestration_agent_capabilities.list_available_workspace_skills",
            side_effect=RuntimeError("catalog provider failed"),
        ):
            unavailable = enabled_workspace_skill_catalog(
                workspace_id="default",
                start_path=Path("/tmp/repo"),
                app_id="skills",
            )

        self.assertEqual((empty.state, empty.skill_ids), (CATALOG_AVAILABLE, ()))
        self.assertEqual((unavailable.state, unavailable.skill_ids), (CATALOG_UNAVAILABLE, ()))

    def test_restricted_explicit_skills_are_intersected_with_enabled_catalog(self) -> None:
        catalog = build_orchestration_planner_catalog(
            _root(skill_ids=["storage-ops", "deleted-skill"]),
            [],
            enabled_skills=EnabledWorkspaceSkillCatalog(
                state=CATALOG_AVAILABLE,
                skill_ids=("browser-ops", "storage-ops"),
            ),
        )

        prompt = catalog.initial_page().text

        self.assertIn("storage-ops", prompt)
        self.assertNotIn("deleted-skill", prompt)
        self.assertIn("enabled count=1", prompt)

    def test_empty_and_unavailable_catalogs_have_distinct_explicit_states(self) -> None:
        empty = build_orchestration_planner_catalog(
            _root(skill_ids=["deleted-skill"]),
            [],
            enabled_skills=EnabledWorkspaceSkillCatalog(
                state=CATALOG_AVAILABLE,
                skill_ids=(),
            ),
        )
        unavailable = build_orchestration_planner_catalog(
            _root(skill_ids=["storage-ops"]),
            [],
            enabled_skills=EnabledWorkspaceSkillCatalog(
                state=CATALOG_UNAVAILABLE,
                skill_ids=(),
            ),
        )

        self.assertIn("none available", empty.initial_page().text)
        self.assertNotIn("catalog unavailable", empty.initial_page().text)
        self.assertIn("catalog unavailable", unavailable.initial_page().text)
        self.assertNotIn("any enabled workspace skill", unavailable.initial_page().text)

    def test_catalog_pages_are_globally_bounded_and_preserve_every_skill_id(self) -> None:
        skill_ids = tuple(f"skill-{index:03d}-" + "x" * 48 for index in range(200))
        items = [
            {
                "id": f"agent-{index:02d}",
                "name": f"Agent {index:02d}",
                "description": "A specialist with an intentionally verbose description. " * 4,
                "skill_ids": [],
                "skill_activation_mode": "explicit",
                "enabled": True,
            }
            for index in range(50)
        ]
        catalog = build_orchestration_planner_catalog(
            _root(),
            items,
            enabled_skills=EnabledWorkspaceSkillCatalog(
                state=CATALOG_AVAILABLE,
                skill_ids=skill_ids,
            ),
        )

        pages = [catalog.initial_page()]
        queued = list(pages[0].next_cursors)
        seen_cursors: set[str] = set()
        while queued:
            cursor = queued.pop(0)
            if cursor in seen_cursors:
                continue
            seen_cursors.add(cursor)
            page = catalog.page(cursor)
            pages.append(page)
            queued.extend(page.next_cursors)

        combined = "\n".join(page.text for page in pages)
        self.assertTrue(all(len(page.text) <= MAX_PLANNER_CATALOG_PAGE_CHARS for page in pages))
        self.assertTrue(all(skill_id in combined for skill_id in skill_ids))
        self.assertTrue(all(f"agent-{index:02d}" in combined for index in range(50)))
        self.assertGreater(len(pages), 1)
        self.assertEqual(catalog.initial_page().text.count(skill_ids[0]), 1)
        self.assertNotRegex(combined, re.compile(r"…\(\+\d+ more\)"))


if __name__ == "__main__":
    unittest.main()
