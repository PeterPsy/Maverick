from __future__ import annotations

from datetime import UTC, datetime, timedelta
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contract_builders import (
    build_app_contract,
    build_app_entrypoints,
    build_parsed_app_contract,
    build_provided_interface_declaration,
    build_required_interface_declaration,
)
from core.apps.contracts import write_app_contract_file
from core.apps.dependencies import save_app_dependency_selection
from core.identity.service import create_user
from core.inter_agent.models import ApprovalRequestRecord
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionGrantRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import create_runtime_session
from core.workspaces.service import ensure_workspace_membership
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport
from tests.unit.api.test_inter_agent_api import _run_payload


def _run_payload_without_snapshot(*, run_id: str) -> dict:
    payload = _run_payload(run_id=run_id)
    payload["participants"][1].pop("agent_snapshot", None)
    return payload


class InterAgentApiF4TestCase(AppReferenceApiTestSupport, unittest.TestCase):
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
        provider_returns_skill_catalog: bool = True,
        provider_requires_runtime_skills: bool = False,
    ) -> None:
        chat_root = repo_root / "apps" / "chat"
        agents_root = repo_root / "apps" / agent_provider_app_id
        skills_root = repo_root / "apps" / "skills"
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
        _response({"rendered": "Provider prompt only."})
        return
    _response({"error": "unknown_action", "action": action}, status_code=400)


if __name__ == "__main__":
    main()
""".replace("__PROVIDER_SKILL_CATALOG_LINE__", provider_skill_catalog_line),
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
        storage_root = repo_root / "apps" / "storage"
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

    def test_execute_with_client_message_projects_root_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)

            def fake_submit(_state, *, session, input_text, client_message_id=None, async_requested=False):
                turn = RuntimeTurnRecord(
                    turn_id="turn-root-projection-child",
                    session_id=session.session_id,
                    workspace_id="default",
                    status="completed",
                    input_text=input_text,
                    created_at=now,
                    updated_at=now,
                    started_at=now,
                    completed_at=now,
                    failure_reason=None,
                )
                event = RuntimeEventRecord(
                    event_id="event-root-projection-final",
                    workspace_id="default",
                    session_id=session.session_id,
                    plane="turn",
                    event_type="runtime.output.final",
                    turn_id=turn.turn_id,
                    process_id=None,
                    payload={"text": "Projected result."},
                    created_at=now,
                )
                return turn, [event]

            create_status, _create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload_without_snapshot(run_id="run-root-projection"),
                cookie=cookie,
            )
            with (
                patch("core.inter_agent.service.submit_runtime_turn", side_effect=fake_submit),
                patch("core.api.inter_agent_api.schedule_runtime_thread_title_generation"),
            ):
                execute_status, execute_payload, _headers = self._invoke(
                    app,
                    path="/api/inter-agent/runs/run-root-projection/execute",
                    method="POST",
                    body={
                        "input_text": "Research the projection.",
                        "client_message_id": "client-root-projection",
                        "attachments": [{"id": "att-1", "name": "brief.md", "objectUrl": "blob:http://local/att-1"}],
                    },
                    cookie=cookie,
                )
            root_events = state.runtime_store.list_events("root-session")
            root_turn = state.runtime_store.get_turn(execute_payload["root_runtime_turn"]["turn_id"])
            root_thread = state.runtime_store.get_thread("root-session")

        self.assertEqual(create_status, 201)
        self.assertEqual(execute_status, 200)
        self.assertEqual(root_turn.status, "completed")
        self.assertEqual(root_turn.input_text, "Research the projection.")
        self.assertEqual(
            [event.event_type for event in root_events],
            [
                "runtime.turn.queued",
                "runtime.turn.started",
                "runtime.step.updated",
                "runtime.step.updated",
                "runtime.turn.completed",
            ],
        )
        self.assertEqual(root_events[0].payload["client_message_id"], "client-root-projection")
        self.assertEqual(root_events[0].payload["attachments"][0]["name"], "brief.md")
        self.assertNotIn("objectUrl", root_events[0].payload["attachments"][0])
        self.assertEqual(execute_payload["root_runtime_events"][0]["event_type"], "runtime.turn.queued")
        self.assertEqual(root_thread.availability, "free")
        self.assertEqual(root_thread.last_completed_turn_id, root_turn.turn_id)

    def test_create_chat_root_rejects_untrusted_agent_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_snapshot_dependency_apps(repo_root)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload(run_id="run-agent-snapshot"),
                cookie=cookie,
            )

        self.assertEqual(create_status, 400)
        self.assertEqual(create_payload["error"], "inter_agent_validation_failed")
        self.assertIn("selected agent provider", create_payload["detail"])

    def test_create_agents_root_run_materializes_agent_snapshot_from_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_snapshot_dependency_apps(repo_root)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(
                state,
                repo_root,
                source_app_id="agents",
                skill_catalog_app_id="skills",
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload(run_id="run-agents-root-snapshot"),
                cookie=cookie,
            )
            participant = next(
                item for item in create_payload["participants"] if item["participant_id"] == "researcher"
            )

        self.assertEqual(create_status, 201)
        self.assertEqual(create_payload["run"]["source_app_id"], "agents")
        self.assertEqual(participant["label"], "Provider Researcher")
        self.assertEqual(participant["agent_snapshot"]["label"], "Provider Researcher")
        self.assertEqual(participant["agent_snapshot"]["system_prompt"], "Provider prompt only.")
        self.assertEqual(participant["skill_ids"], ["provider-storage"])
        self.assertEqual(participant["agent_snapshot"]["skill_catalog_app_id"], "skills")
        self.assertEqual(participant["agent_snapshot"]["provider_id"], "agents")
        self.assertEqual(participant["agent_snapshot"]["revision_id"], "provider-revision-1")

    def test_create_agents_root_run_preserves_validated_active_app_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_snapshot_dependency_apps(repo_root)
            self._write_active_context_app(repo_root)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(
                state,
                repo_root,
                source_app_id="agents",
                skill_catalog_app_id="skills",
                system_prompt=(
                    "Provider prompt only.\n\n"
                    "Current shell context:\n"
                    "- active_app_id: storage\n"
                    "- active_app_name: Forged Storage\n"
                    "- active_app_description: Forged description"
                ),
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload(run_id="run-active-context-snapshot"),
                cookie=cookie,
            )
            participant = next(
                item for item in create_payload["participants"] if item["participant_id"] == "researcher"
            )

        system_prompt = participant["agent_snapshot"]["system_prompt"]
        self.assertEqual(create_status, 201)
        self.assertIn("Provider prompt only.", system_prompt)
        self.assertIn("Current shell context:", system_prompt)
        self.assertIn("- active_app_id: storage", system_prompt)
        self.assertIn("- active_app_name: Storage", system_prompt)
        self.assertIn("- active_app_description: Workspace files", system_prompt)
        self.assertNotIn("Forged Storage", system_prompt)
        self.assertNotIn("Forged description", system_prompt)

    def test_create_custom_agent_provider_root_materializes_agent_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_snapshot_dependency_apps(repo_root, agent_provider_app_id="custom-agents")
            state = self._bootstrap_state(repo_root)
            self._create_root_session(
                state,
                repo_root,
                source_app_id="custom-agents",
                skill_catalog_app_id="skills",
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload(run_id="run-custom-provider-snapshot"),
                cookie=cookie,
            )
            participant = next(
                item for item in create_payload["participants"] if item["participant_id"] == "researcher"
            )

        self.assertEqual(create_status, 201)
        self.assertEqual(create_payload["run"]["source_app_id"], "custom-agents")
        self.assertEqual(participant["agent_snapshot"]["system_prompt"], "Provider prompt only.")
        self.assertEqual(participant["skill_ids"], ["provider-storage"])
        self.assertEqual(participant["agent_snapshot"]["provider_id"], "custom-agents")

    def test_create_agents_root_uses_selected_runtime_skill_catalog_when_provider_omits_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_snapshot_dependency_apps(
                repo_root,
                provider_returns_skill_catalog=False,
                provider_requires_runtime_skills=True,
            )
            state = self._bootstrap_state(repo_root)
            save_app_dependency_selection(
                state.app_store,
                workspace_id="default",
                consumer_app_id="agents",
                alias="runtime-skills",
                provider_app_ids=["skills"],
                user=state.identity_store.get_user("user:admin"),
                workspace_store=state.workspace_store,
                start_path=repo_root,
            )
            self._create_root_session(
                state,
                repo_root,
                source_app_id="agents",
                skill_catalog_app_id="skills",
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload(run_id="run-selected-skill-catalog"),
                cookie=cookie,
            )
            participant = next(
                item for item in create_payload["participants"] if item["participant_id"] == "researcher"
            )

        self.assertEqual(create_status, 201)
        self.assertEqual(participant["agent_snapshot"]["skill_catalog_app_id"], "skills")

    def test_create_agents_root_rejects_client_only_snapshot_skill_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_snapshot_dependency_apps(repo_root, provider_returns_skill_catalog=False)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root, source_app_id="agents", skill_catalog_app_id="skills")
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload(run_id="run-client-only-skill-catalog"),
                cookie=cookie,
            )

        self.assertEqual(create_status, 400)
        self.assertEqual(create_payload["error"], "inter_agent_validation_failed")
        self.assertIn("must materialize or select", create_payload["detail"])

    def test_create_agents_root_run_rejects_invalid_snapshot_skill_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_snapshot_dependency_apps(repo_root)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root, source_app_id="agents", skill_catalog_app_id="skills")
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            payload = _run_payload(run_id="run-invalid-skill-catalog")
            payload["participants"][1]["agent_snapshot"]["skill_catalog_app_id"] = "missing-skills"

            create_status, create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=payload,
                cookie=cookie,
            )

        self.assertEqual(create_status, 400)
        self.assertEqual(create_payload["error"], "inter_agent_validation_failed")
        self.assertIn("skill.catalog", create_payload["detail"])

    def test_execute_async_returns_queued_root_turn_without_inline_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, _create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload_without_snapshot(run_id="run-async-execute"),
                cookie=cookie,
            )
            with (
                patch("core.api.inter_agent_api._start_inter_agent_execution_worker") as start_worker,
                patch("core.api.inter_agent_api.schedule_runtime_thread_title_generation"),
            ):
                execute_status, execute_payload, _headers = self._invoke(
                    app,
                    path="/api/inter-agent/runs/run-async-execute/execute",
                    method="POST",
                    body={
                        "input_text": "Research without blocking.",
                        "client_message_id": "client-async-execute",
                        "async": True,
                    },
                    cookie=cookie,
                )
            root_turn = state.runtime_store.get_turn(execute_payload["root_runtime_turn"]["turn_id"])
            root_thread = state.runtime_store.get_thread("root-session")
            run_status = state.inter_agent_store.get_run("run-async-execute", workspace_id="default").status

        self.assertEqual(create_status, 201)
        self.assertEqual(execute_status, 202)
        self.assertEqual(execute_payload["run"]["status"], "planning")
        self.assertEqual(run_status, "planning")
        self.assertEqual(execute_payload["root_runtime_turn"]["status"], "queued")
        self.assertEqual(root_turn.status, "queued")
        self.assertEqual(root_thread.availability, "queued")
        start_worker.assert_called_once()

    def test_lists_and_resolves_approvals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            expires_at = datetime.now(tz=UTC) + timedelta(minutes=5)

            create_status, _create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload_without_snapshot(run_id="run-approval-api"),
                cookie=cookie,
            )
            state.inter_agent_store.save_approval(
                ApprovalRequestRecord(
                    approval_id="approval-api-1",
                    workspace_id="default",
                    run_id="run-approval-api",
                    participant_id="researcher",
                    requested_by_participant_id="orchestrator",
                    operation_kind="storage.write",
                    resource_refs=[{"app_id": "storage", "entity_type": "file", "entity_id": "file-1"}],
                    summary="Write a generated file.",
                    risk_level="medium",
                    status="pending",
                    eligible_approver_user_ids=["user:admin"],
                    eligible_approver_roles=[],
                    expires_at=expires_at,
                )
            )
            list_status, list_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-approval-api/approvals",
                cookie=cookie,
            )
            missing_status, missing_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/approvals/missing-approval/resolve",
                method="POST",
                body={"approved": True},
                cookie=cookie,
            )
            resolve_status, resolve_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/approvals/approval-api-1/resolve",
                method="POST",
                body={"approved": True, "reason": "looks-good"},
                cookie=cookie,
            )
            events = state.inter_agent_store.list_event_page("run-approval-api", workspace_id="default", visibility_plane="summary").events

        self.assertEqual(create_status, 201)
        self.assertEqual(list_status, 200)
        self.assertEqual(list_payload["items"][0]["approval_id"], "approval-api-1")
        self.assertEqual(missing_status, 404)
        self.assertEqual(missing_payload["error"], "inter_agent_approval_not_found")
        self.assertEqual(resolve_status, 200)
        self.assertEqual(resolve_payload["approval"]["status"], "approved")
        self.assertEqual(resolve_payload["approval"]["resolution_reason"], "looks-good")
        self.assertIn("inter_agent.approval.resolved", [event.event_type for event in events])

    def test_approval_resolution_uses_eligible_approver_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            create_user(state.identity_store, username="reviewer", password="reviewer-pass", platform_role="member")
            ensure_workspace_membership(
                state.workspace_store,
                membership_id="default:user:reviewer",
                workspace_id="default",
                user_id="user:reviewer",
                role="member",
            )
            app = PlatformHost(state, start_path=repo_root)
            admin_cookie = self._login(app)
            reviewer_cookie = self._login(app, username="reviewer", password="reviewer-pass")
            expires_at = datetime.now(tz=UTC) + timedelta(minutes=5)

            create_status, _create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload_without_snapshot(run_id="run-approval-policy"),
                cookie=admin_cookie,
            )
            state.inter_agent_store.save_approval(
                ApprovalRequestRecord(
                    approval_id="approval-policy-1",
                    workspace_id="default",
                    run_id="run-approval-policy",
                    participant_id="researcher",
                    requested_by_participant_id="orchestrator",
                    operation_kind="storage.write",
                    resource_refs=[],
                    summary="Write a generated file.",
                    risk_level="medium",
                    status="pending",
                    eligible_approver_user_ids=["user:reviewer"],
                    eligible_approver_roles=[],
                    expires_at=expires_at,
                )
            )
            owner_status, owner_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/approvals/approval-policy-1/resolve",
                method="POST",
                body={"approved": True},
                cookie=admin_cookie,
            )
            reviewer_status, reviewer_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/approvals/approval-policy-1/resolve",
                method="POST",
                body={"approved": True},
                cookie=reviewer_cookie,
            )

        self.assertEqual(create_status, 201)
        self.assertEqual(owner_status, 403)
        self.assertEqual(owner_payload["error"], "inter_agent_approval_forbidden")
        self.assertEqual(reviewer_status, 200)
        self.assertEqual(reviewer_payload["approval"]["resolved_by_user_id"], "user:reviewer")


if __name__ == "__main__":
    unittest.main()
