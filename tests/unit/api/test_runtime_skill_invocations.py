from __future__ import annotations

from datetime import UTC, datetime
import json
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import create_runtime_session
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeSkillInvocationApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def test_unknown_skill_fails_before_provider_submission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._state(repo_root)
            session = create_runtime_session(
                state.runtime_store,
                session_id="skill-session",
                workspace_id="default",
                agent_id="chat",
                owner_user_id="user:admin",
                skill_activation_mode="explicit",
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=AssertionError("must fail before submit")):
                status, payload, _headers = self._invoke(
                    app,
                    path=f"/api/runtime/sessions/{session.session_id}/turns",
                    method="POST",
                    body={"input_text": "$missing run", "invoked_skill_ids": ["missing"], "async": True},
                    cookie=cookie,
                )

        self.assertEqual(status, 400)
        self.assertEqual(payload, {"error": "invoked_skill_unavailable"})

    def test_disabled_skill_fails_before_provider_submission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_skill(repo_root, "storage-ops", enabled=False)
            state = self._state(repo_root)
            session = create_runtime_session(
                state.runtime_store,
                session_id="disabled-skill-session",
                workspace_id="default",
                agent_id="chat",
                owner_user_id="user:admin",
                skill_activation_mode="explicit",
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=AssertionError("must fail before submit")):
                status, payload, _headers = self._invoke(
                    app,
                    path=f"/api/runtime/sessions/{session.session_id}/turns",
                    method="POST",
                    body={"input_text": "$storage-ops run", "invoked_skill_ids": ["storage-ops"], "async": True},
                    cookie=cookie,
                )

        self.assertEqual(status, 400)
        self.assertEqual(payload, {"error": "invoked_skill_unavailable"})

    def test_skill_outside_session_allowlist_fails_before_provider_submission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_skill(repo_root, "storage-ops", enabled=True)
            state = self._state(repo_root)
            session = create_runtime_session(
                state.runtime_store,
                session_id="allowlisted-skill-session",
                workspace_id="default",
                agent_id="chat",
                owner_user_id="user:admin",
                skill_ids=["review-ops"],
                skill_activation_mode="explicit",
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=AssertionError("must fail before submit")):
                status, payload, _headers = self._invoke(
                    app,
                    path=f"/api/runtime/sessions/{session.session_id}/turns",
                    method="POST",
                    body={"input_text": "$storage-ops run", "invoked_skill_ids": ["storage-ops"], "async": True},
                    cookie=cookie,
                )

        self.assertEqual(status, 400)
        self.assertEqual(payload, {"error": "invoked_skill_not_allowed"})

    def test_plain_hosted_session_rejects_explicit_skill_invocations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_skill(repo_root, "storage-ops", enabled=True)
            state = self._state(repo_root)
            session = create_runtime_session(
                state.runtime_store,
                session_id="plain-hosted-skill-session",
                workspace_id="default",
                agent_id="chat",
                owner_user_id="user:admin",
                runtime_mode="plain_hosted_chat",
                skill_activation_mode="explicit",
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=AssertionError("must fail before submit")):
                status, payload, _headers = self._invoke(
                    app,
                    path=f"/api/runtime/sessions/{session.session_id}/turns",
                    method="POST",
                    body={"input_text": "$storage-ops run", "invoked_skill_ids": ["storage-ops"], "async": True},
                    cookie=cookie,
                )

        self.assertEqual(status, 400)
        self.assertEqual(payload, {"error": "plain_hosted_chat_blocks_skills"})

    def test_enabled_allowed_skill_id_is_forwarded_without_a_client_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_skill(repo_root, "storage-ops", enabled=True)
            state = self._state(repo_root)
            session = create_runtime_session(
                state.runtime_store,
                session_id="skill-session",
                workspace_id="default",
                agent_id="chat",
                owner_user_id="user:admin",
                skill_ids=["storage-ops"],
                skill_activation_mode="explicit",
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            captured: dict[str, object] = {}

            def fake_submit(_state, **kwargs):
                captured.update(kwargs)
                now = datetime.now(tz=UTC)
                return RuntimeTurnRecord(
                    turn_id="turn-skill",
                    session_id=session.session_id,
                    workspace_id=session.workspace_id,
                    status="queued",
                    input_text=kwargs["input_text"],
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    completed_at=None,
                    failure_reason=None,
                    invoked_skill_ids=list(kwargs["invoked_skill_ids"]),
                ), []

            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=fake_submit):
                status, _payload, _headers = self._invoke(
                    app,
                    path=f"/api/runtime/sessions/{session.session_id}/turns",
                    method="POST",
                    body={"input_text": "$storage-ops run", "invoked_skill_ids": ["storage-ops"], "async": True},
                    cookie=cookie,
                )

        self.assertEqual(status, 202)
        self.assertEqual(captured["invoked_skill_ids"], ["storage-ops"])
        self.assertNotIn("path", captured)

    def test_free_form_marker_without_ids_stays_visible_but_has_no_structured_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_skill(repo_root, "storage-ops", enabled=True)
            state = self._state(repo_root)
            session = create_runtime_session(
                state.runtime_store,
                session_id="skill-marker-only-session",
                workspace_id="default",
                agent_id="chat",
                owner_user_id="user:admin",
                skill_activation_mode="explicit",
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            captured: dict[str, object] = {}

            def fake_submit(_state, **kwargs):
                captured.update(kwargs)
                now = datetime.now(tz=UTC)
                return RuntimeTurnRecord(
                    turn_id="turn-marker-only",
                    session_id=session.session_id,
                    workspace_id=session.workspace_id,
                    status="queued",
                    input_text=kwargs["input_text"],
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    completed_at=None,
                    failure_reason=None,
                    invoked_skill_ids=list(kwargs["invoked_skill_ids"]),
                ), []

            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=fake_submit):
                status, payload, _headers = self._invoke(
                    app,
                    path=f"/api/runtime/sessions/{session.session_id}/turns",
                    method="POST",
                    body={"input_text": "$storage-ops run", "async": True},
                    cookie=cookie,
                )

        self.assertEqual(status, 202)
        self.assertEqual(captured["input_text"], "$storage-ops run")
        self.assertEqual(captured["invoked_skill_ids"], [])
        self.assertEqual(payload["turn"]["input_text"], "$storage-ops run")
        self.assertEqual(payload["turn"]["invoked_skill_ids"], [])

    def _state(self, repo_root):
        with patch.dict(
            "os.environ",
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            return bootstrap_platform_state(start_path=repo_root)

    @staticmethod
    def _write_skill(repo_root, skill_id: str, *, enabled: bool) -> None:
        data_root = repo_root / "workspaces" / "default" / "data" / "skills"
        skill_root = data_root / "skills" / skill_id
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text(f"# {skill_id}\n", encoding="utf-8")
        (data_root / "state.json").write_text(
            json.dumps({"schema_version": "1", "skills": [{"id": skill_id, "enabled": enabled}]}),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
