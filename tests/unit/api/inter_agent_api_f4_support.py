from __future__ import annotations

import json
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.apps.contract_builders import (
    build_app_contract,
    build_app_entrypoints,
    build_parsed_app_contract,
    build_provided_interface_declaration,
    build_required_interface_declaration,
)
from core.apps.contracts import write_app_contract_file
from core.runtime.runtime_session import RuntimeSessionGrantRecord
from core.runtime.service import create_runtime_session
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport
from tests.unit.api.test_inter_agent_api import _run_payload


def run_payload_without_snapshot(*, run_id: str) -> dict:
    payload = _run_payload(run_id=run_id)
    payload["participants"][1].pop("agent_snapshot", None)
    return payload


class InterAgentApiF4Fixture(AppReferenceApiTestSupport):
    def _bootstrap_state(self, repo_root):
        with patch.dict(
            "os.environ",
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            return bootstrap_platform_state(start_path=repo_root)

    def _write_snapshot_dependency_apps(
        self,
        repo_root,
        *,
        agent_provider_app_id: str = "agents",
        provider_prompt: str = "Provider prompt only.",
        provider_returns_skill_catalog: bool = True,
        provider_requires_runtime_skills: bool = False,
    ) -> None:
        apps_root = repo_root / "apps"
        chat_root = apps_root / "chat"
        agents_root = apps_root / agent_provider_app_id
        skills_root = apps_root / "skills"
        chat_root.mkdir(parents=True, exist_ok=True)
        agents_root.mkdir(parents=True, exist_ok=True)
        skills_root.mkdir(parents=True, exist_ok=True)
        agents_backend = agents_root / "backend" / "app_backend.py"
        agents_backend.parent.mkdir(parents=True, exist_ok=True)
        provider_skill_catalog_line = (
            '                    "skill_catalog_app_id": "skills",\n'
            if provider_returns_skill_catalog
            else ""
        )
        provider_prompt_literal = json.dumps(provider_prompt)
        agents_backend.write_text(
            """from __future__ import annotations

import json
import sys


def _response(payload: dict, *, status_code: int = 200) -> None:
    print(json.dumps({"status_code": status_code, "json": payload}))


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    action = str(body.get("action") or "")
    requested = str(body.get("id") or body.get("agent_type_id") or "").strip()
    if action == "get_agent_definition":
        if requested != "research-agent":
            _response({"exists": False, "agent_type_id": requested})
            return
        _response(
            {
                "exists": True,
                "agent_definition": {
                    "id": "research-agent",
                    "name": "Provider Researcher",
                    "description": "Materialized by provider.",
                    "skill_ids": ["provider-storage"],
__PROVIDER_SKILL_CATALOG_LINE__                    "enabled": True,
                    "updated_at": "provider-revision-1",
                },
            }
        )
        return
    if action == "preview_prompt":
        if requested != "research-agent":
            _response({"rendered": ""}, status_code=404)
            return
        _response({"rendered": __PROVIDER_PROMPT__})
        return
    _response({"error": "unknown_action", "action": action}, status_code=400)


if __name__ == "__main__":
    main()
"""
            .replace("__PROVIDER_SKILL_CATALOG_LINE__", provider_skill_catalog_line)
            .replace("__PROVIDER_PROMPT__", provider_prompt_literal),
            encoding="utf-8",
        )
        write_app_contract_file(
            chat_root,
            build_parsed_app_contract(
                app_id="chat",
                name="Chat",
                version="0.2.0",
                description="Chat test app.",
                publisher="maverick",
                contract=build_app_contract(
                    requires=[
                        build_required_interface_declaration(
                            alias="agent-catalog",
                            interface="agent.catalog",
                            required=False,
                            description="Agent catalog.",
                        ),
                        build_required_interface_declaration(
                            alias="agent-prompt-materializer",
                            interface="agent.prompt-materializer",
                            required=False,
                            description="Agent prompt materializer.",
                        ),
                    ]
                ),
            ),
        )
        write_app_contract_file(
            agents_root,
            build_parsed_app_contract(
                app_id=agent_provider_app_id,
                name="Agents",
                version="0.1.0",
                description="Agents test app.",
                publisher="maverick",
                contract=build_app_contract(
                    entrypoints=build_app_entrypoints(backend="backend/app_backend.py"),
                    requires=(
                        [
                            build_required_interface_declaration(
                                alias="runtime-skills",
                                interface="skill.catalog",
                                required=True,
                                description="Runtime skill catalog.",
                            )
                        ]
                        if provider_requires_runtime_skills
                        else []
                    ),
                    provides=[
                        build_provided_interface_declaration(
                            interface="agent.catalog",
                            description="Agent catalog.",
                            surfaces=["backend"],
                        ),
                        build_provided_interface_declaration(
                            interface="agent.prompt-materializer",
                            description="Agent prompt materializer.",
                            surfaces=["backend"],
                        ),
                    ]
                ),
            ),
        )
        write_app_contract_file(
            skills_root,
            build_parsed_app_contract(
                app_id="skills",
                name="Skills",
                version="0.1.0",
                description="Skills test app.",
                publisher="maverick",
                contract=build_app_contract(
                    provides=[
                        build_provided_interface_declaration(
                            interface="skill.catalog",
                            description="Skill catalog.",
                            surfaces=["backend"],
                        )
                    ]
                ),
            ),
        )

    def _write_active_context_app(self, repo_root) -> None:
        storage_root = (repo_root / "apps") / "storage"
        storage_root.mkdir(parents=True, exist_ok=True)
        write_app_contract_file(
            storage_root,
            build_parsed_app_contract(
                app_id="storage",
                name="Storage",
                version="0.1.0",
                description="Workspace files",
                publisher="maverick",
                contract=build_app_contract(),
            ),
        )

    def _create_root_session(
        self,
        state,
        repo_root,
        *,
        source_app_id: str = "chat",
        skill_catalog_app_id: str | None = None,
        system_prompt: str = "Parent prompt must not leak.",
    ) -> None:
        create_runtime_session(
            state.runtime_store,
            session_id="root-session",
            workspace_id="default",
            agent_id="chat",
            source_app_id=source_app_id,
            system_prompt=system_prompt,
            skill_ids=["parent-skill"],
            skill_catalog_app_id=skill_catalog_app_id,
            owner_user_id="parent-owner",
            grants=[
                RuntimeSessionGrantRecord(
                    operation="cleanup",
                    grantee_kind="user",
                    grantee_id="parent-owner",
                    issued_by_user_id="parent-owner",
                )
            ],
            governance=state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )
