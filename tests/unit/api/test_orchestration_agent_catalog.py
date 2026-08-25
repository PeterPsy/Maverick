from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.orchestration_agent_catalog import build_orchestration_agent_catalog
from core.inter_agent.models import AgentParticipantSnapshot
from core.inter_agent.orchestration_agent_capabilities import root_prompt_entry
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec


class OrchestrationAgentCatalogTest(unittest.TestCase):
    def test_explicit_default_agent_lists_enabled_catalog_ids_when_allowlist_is_open(self) -> None:
        entry = root_prompt_entry(
            AgentParticipantSnapshot(
                agent_type_id="generalist",
                label="Generalist",
                system_prompt="Work carefully.",
                skill_ids=[],
                skill_catalog_app_id="skills",
                skill_activation_mode="explicit",
            ),
            default_skill_ids=["storage-ops", "browser-ops"],
        )

        self.assertIn("allowed skill ids=browser-ops,storage-ops", entry)

    def test_lists_compact_candidates_and_materializes_selected_snapshot_server_side(self) -> None:
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
                            "skill_ids": ["storage"],
                            "enabled": True,
                            "updated_at": "2026-08-02T00:00:00Z",
                        },
                    }
                }
            return {"json": {"rendered": "You are the server-owned coder specialist."}}

        with (
            patch("core.api.orchestration_agent_catalog.resolve_app_dependencies", return_value=dependencies),
            patch("core.api.orchestration_agent_catalog.invoke_dependency_backend_request", side_effect=invoke),
            patch(
                "core.api.orchestration_agent_catalog.selected_runtime_skill_catalog_app_id_for_source_app",
                return_value="skills",
            ),
            patch(
                "core.api.orchestration_agent_catalog.validate_runtime_skill_catalog_provider_app_id",
                return_value="skills",
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

        self.assertEqual(catalog.prompt_entries, (
            "default (omit agent_type_id): generalist: Generalist "
            "[skill mode=implicit; assigned skill ids=storage]",
            "agent-type-coder: Coder Specialist — Implements and tests code changes. "
            "[skill mode=explicit; allowed skill ids=storage-ops]",
        ))
        self.assertEqual(selected.agent_type_id, "agent-type-coder")
        self.assertEqual(selected.system_prompt, "You are the server-owned coder specialist.")
        self.assertEqual(selected.skill_ids, ["storage"])
        self.assertEqual(selected.provider_id, "agents")


if __name__ == "__main__":
    unittest.main()
