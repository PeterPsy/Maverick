from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.orchestration_agent_catalog import build_orchestration_agent_catalog
from core.inter_agent.models import AgentParticipantSnapshot
from core.inter_agent.orchestration_agent_capabilities import (
    CATALOG_AVAILABLE,
    EnabledWorkspaceSkillCatalog,
    build_orchestration_planner_catalog,
)
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec


class OrchestrationAgentCatalogTest(unittest.TestCase):
    def test_explicit_default_agent_references_shared_enabled_catalog_scope(self) -> None:
        catalog = build_orchestration_planner_catalog(
            AgentParticipantSnapshot(
                agent_type_id="generalist",
                label="Generalist",
                system_prompt="Work carefully.",
                skill_ids=[],
                skill_catalog_app_id="skills",
                skill_activation_mode="explicit",
            ),
            [],
            enabled_skills=EnabledWorkspaceSkillCatalog(
                state=CATALOG_AVAILABLE,
                skill_ids=("storage-ops", "browser-ops"),
            ),
        )
        entry = catalog.agent_entries[0].text

        self.assertIn("invocable skill scope=s0", entry)
        self.assertIn("enabled count=2", entry)
        self.assertNotIn("browser-ops", entry)

    def test_planner_and_resolver_share_the_same_materialized_revision(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        run = InterAgentService(store).create_run(orchestrated_spec())
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        state = SimpleNamespace(
            app_store=object(),
            workspace_store=object(),
            identity_store=SimpleNamespace(get_user=lambda _user_id: SimpleNamespace(user_id="user-1")),
        )
        dependencies = {
            "dependencies": [
                {
                    "alias": alias,
                    "status": "resolved",
                    "selected_provider_app_ids": ["agents"],
                }
                for alias in ("agent-catalog", "agent-prompt-materializer")
            ]
        }

        def invoke(_state, **kwargs):
            action = kwargs["body"]["action"]
            if action == "catalog.compact":
                return {
                    "json": {
                        "agent_types": [
                            {
                                "id": "agent-type-coder",
                                "name": "Coder Specialist",
                                "description": "Implements and tests code changes.",
                                "skill_ids": ["storage-ops"],
                                "skill_activation_mode": "explicit",
                                "enabled": True,
                                "revision_id": "revision-1",
                            }
                        ]
                    }
                }
            if action == "get_agent_definition":
                return {
                    "json": {
                        "exists": True,
                        "agent_definition": {
                            "id": "agent-type-coder",
                            "name": "Coder Specialist",
                            "description": "Implements and tests code changes.",
                            "skill_ids": ["storage-ops"],
                            "skill_activation_mode": "explicit",
                            "enabled": True,
                            "updated_at": "2026-08-02T00:00:00Z",
                            "revision_id": "revision-1",
                        },
                    }
                }
            return {
                "json": {
                    "rendered": "You are the server-owned coder specialist.",
                    "revision_id": "revision-1",
                }
            }

        with (
            patch("core.api.orchestration_agent_catalog.resolve_app_dependencies", return_value=dependencies),
            patch("core.api.orchestration_agent_catalog_provider.invoke_dependency_backend_request", side_effect=invoke),
            patch(
                "core.api.orchestration_agent_catalog_provider.selected_runtime_skill_catalog_app_id_for_source_app",
                return_value="skills",
            ),
            patch(
                "core.api.orchestration_agent_catalog_provider.validate_runtime_skill_catalog_provider_app_id",
                return_value="skills",
            ),
            patch(
                "core.api.orchestration_agent_catalog_materialization.enabled_workspace_skill_catalog",
                return_value=EnabledWorkspaceSkillCatalog(
                    state=CATALOG_AVAILABLE,
                    skill_ids=("storage-ops",),
                ),
            ),
        ):
            catalog = build_orchestration_agent_catalog(
                state,
                workspace_id="default",
                created_by_user_id="user-1",
                root_session=SimpleNamespace(source_app_id="agents", system_prompt="Root prompt."),
                orchestrator=orchestrator,
                start_path=make_temp_repo_root(self),
            )
            selected = catalog.resolve("agent-type-coder")

        self.assertEqual(tuple(entry.text for entry in catalog.planner_catalog.agent_entries), (
            "default (omit agent_type_id): generalist: Generalist "
            "[skill mode=implicit; skills are runtime-managed; omit invoked_skill_ids]",
            "agent-type-coder: Coder Specialist — Implements and tests code changes. "
            "[skill mode=explicit; invocable skill scope=s0; enabled count=1; catalog cursor=skills:s0:0]",
        ))
        self.assertIn("storage-ops", catalog.planner_catalog.initial_page().text)
        self.assertEqual(selected.agent_type_id, "agent-type-coder")
        self.assertEqual(selected.system_prompt, "You are the server-owned coder specialist.")
        self.assertEqual(selected.skill_ids, ["storage-ops"])
        self.assertEqual(selected.revision_id, "revision-1")
        self.assertEqual(selected.provider_id, "agents")

    def test_retries_when_compact_and_materialized_revisions_change_mid_read(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        run = InterAgentService(store).create_run(orchestrated_spec())
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        state = SimpleNamespace(
            app_store=object(),
            workspace_store=object(),
            identity_store=SimpleNamespace(get_user=lambda _user_id: SimpleNamespace(user_id="user-1")),
        )
        dependencies = {
            "dependencies": [
                {
                    "alias": alias,
                    "status": "resolved",
                    "selected_provider_app_ids": ["agents"],
                }
                for alias in ("agent-catalog", "agent-prompt-materializer")
            ]
        }
        compact_calls = 0

        def invoke(_state, **kwargs):
            nonlocal compact_calls
            action = kwargs["body"]["action"]
            if action == "catalog.compact":
                compact_calls += 1
                revision = "revision-1" if compact_calls == 1 else "revision-2"
                skill_id = "storage-ops" if revision == "revision-1" else "storage"
                return {
                    "json": {
                        "counts": {"agent_types": 1},
                        "agent_types": [
                            {
                                "id": "agent-type-coder",
                                "name": "Coder Specialist",
                                "description": "Implements code.",
                                "skill_ids": [skill_id],
                                "skill_activation_mode": "explicit",
                                "enabled": True,
                                "revision_id": revision,
                            }
                        ],
                    }
                }
            if action == "get_agent_definition":
                return {
                    "json": {
                        "exists": True,
                        "agent_definition": {
                            "id": "agent-type-coder",
                            "name": "Coder Specialist",
                            "description": "Implements code.",
                            "skill_ids": ["storage"],
                            "skill_activation_mode": "explicit",
                            "enabled": True,
                            "revision_id": "revision-2",
                        },
                    }
                }
            return {"json": {"rendered": "Coder revision 2.", "revision_id": "revision-2"}}

        with (
            patch("core.api.orchestration_agent_catalog.resolve_app_dependencies", return_value=dependencies),
            patch("core.api.orchestration_agent_catalog_provider.invoke_dependency_backend_request", side_effect=invoke),
            patch(
                "core.api.orchestration_agent_catalog_provider.selected_runtime_skill_catalog_app_id_for_source_app",
                return_value="skills",
            ),
            patch(
                "core.api.orchestration_agent_catalog_provider.validate_runtime_skill_catalog_provider_app_id",
                return_value="skills",
            ),
            patch(
                "core.api.orchestration_agent_catalog_materialization.enabled_workspace_skill_catalog",
                return_value=EnabledWorkspaceSkillCatalog(
                    state=CATALOG_AVAILABLE,
                    skill_ids=("storage", "storage-ops"),
                ),
            ),
        ):
            catalog = build_orchestration_agent_catalog(
                state,
                workspace_id="default",
                created_by_user_id="user-1",
                root_session=SimpleNamespace(source_app_id="agents", system_prompt="Root prompt."),
                orchestrator=orchestrator,
                start_path=make_temp_repo_root(self),
            )

        selected = catalog.resolve("agent-type-coder")
        self.assertGreaterEqual(compact_calls, 3)
        self.assertEqual(selected.skill_ids, ["storage"])
        self.assertEqual(selected.revision_id, "revision-2")
        self.assertIn("storage", catalog.planner_catalog.initial_page().text)
        self.assertNotIn("storage-ops", catalog.planner_catalog.initial_page().text)


if __name__ == "__main__":
    unittest.main()
