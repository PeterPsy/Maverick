from __future__ import annotations

from datetime import UTC, datetime
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.apps.dependencies import save_app_dependency_selection
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from tests.unit.api.inter_agent_api_f4_support import InterAgentApiF4Fixture, run_payload_without_snapshot
from tests.unit.api.test_inter_agent_api import _run_payload


def _run_payload_without_snapshot(*, run_id: str) -> dict:
    return run_payload_without_snapshot(run_id=run_id)


class InterAgentApiF4TestCase(InterAgentApiF4Fixture, unittest.TestCase):

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

    def test_create_agents_root_run_replaces_provider_active_app_context_block(self) -> None:
        provider_prompt = (
            "Provider prompt only.\n\n"
            "Current shell context:\n"
            "- active_app_id: storage\n"
            "- active_app_name: Provider Storage\n"
            "- active_app_description: Provider description"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_snapshot_dependency_apps(repo_root, provider_prompt=provider_prompt)
            self._write_active_context_app(repo_root)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(
                state,
                repo_root,
                source_app_id="agents",
                skill_catalog_app_id="skills",
                system_prompt=provider_prompt,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=_run_payload(run_id="run-active-context-dedupe"),
                cookie=cookie,
            )

        self.assertEqual(create_status, 201)
        participant = next(item for item in create_payload["participants"] if item["participant_id"] == "researcher")
        system_prompt = participant["agent_snapshot"]["system_prompt"]
        self.assertEqual(system_prompt.count("Current shell context:"), 1)
        self.assertIn("Provider prompt only.", system_prompt)
        self.assertIn("- active_app_id: storage", system_prompt)
        self.assertIn("- active_app_name: Storage", system_prompt)
        self.assertIn("- active_app_description: Workspace files", system_prompt)
        self.assertNotIn("Provider Storage", system_prompt)
        self.assertNotIn("Provider description", system_prompt)

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

if __name__ == "__main__":
    unittest.main()
