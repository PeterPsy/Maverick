from __future__ import annotations

from datetime import UTC, datetime
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.runtime.message_steering import RuntimeMessageSteerAttempt
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.service import create_runtime_session, transition_runtime_turn
from core.runtime.turn_submission_service_queue import _queue_turn_with_event
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeMessageSteeringApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def test_turn_submit_returns_same_turn_delivery_and_steered_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            session = create_runtime_session(
                state.runtime_store,
                session_id="session-steer-api",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                owner_user_id="user:admin",
                governance=state.workspace_store.get_governance("default"),
                platform_allows_full_access=True,
                start_path=repo_root,
            )
            queued_turn, _events = _queue_turn_with_event(
                state,
                session=session,
                input_text="first message",
                provider_id="codex",
                client_message_id="client-first",
                attachments=None,
                app_references=None,
            )
            active_turn = transition_runtime_turn(
                state.runtime_store,
                turn_id=queued_turn.turn_id,
                target_status="active",
            )
            steered_event = RuntimeEventRecord(
                event_id="event-steered-api",
                workspace_id="default",
                session_id=session.session_id,
                plane="turn",
                event_type="runtime.message.steered",
                turn_id=active_turn.turn_id,
                process_id=None,
                payload={"input_text": "new direction", "client_message_id": "client-steer-api"},
                created_at=datetime(2026, 8, 11, tzinfo=UTC),
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            with patch(
                "core.api.runtime_api.attempt_runtime_message_steer",
                return_value=RuntimeMessageSteerAttempt(
                    status="steered",
                    turn=active_turn,
                    events=(steered_event,),
                ),
            ):
                status, payload, _headers = self._invoke(
                    app,
                    path=f"/api/runtime/sessions/{session.session_id}/turns",
                    method="POST",
                    body={
                        "input_text": "new direction",
                        "client_message_id": "client-steer-api",
                        "async": True,
                        "delivery_policy": "steer_or_queue",
                    },
                    cookie=cookie,
                )

        self.assertEqual(status, 202)
        self.assertEqual(payload["delivery"], "steered")
        self.assertEqual(payload["turn"]["turn_id"], active_turn.turn_id)
        self.assertEqual(payload["events"][0]["event_type"], "runtime.message.steered")

    def test_uncertain_delivery_returns_conflict_without_queueing_a_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            session = create_runtime_session(
                state.runtime_store,
                session_id="session-steer-uncertain-api",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                owner_user_id="user:admin",
                governance=state.workspace_store.get_governance("default"),
                platform_allows_full_access=True,
                start_path=repo_root,
            )
            queued_turn, _events = _queue_turn_with_event(
                state,
                session=session,
                input_text="first message",
                provider_id="codex",
                client_message_id="client-first-uncertain",
                attachments=None,
                app_references=None,
            )
            active_turn = transition_runtime_turn(
                state.runtime_store,
                turn_id=queued_turn.turn_id,
                target_status="active",
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            with patch(
                "core.api.runtime_api.attempt_runtime_message_steer",
                return_value=RuntimeMessageSteerAttempt(
                    status="delivery_uncertain",
                    turn=active_turn,
                    reason="provider acknowledgement timed out",
                ),
            ), patch("core.api.runtime_api.submit_runtime_turn_async") as submit:
                status, payload, _headers = self._invoke(
                    app,
                    path=f"/api/runtime/sessions/{session.session_id}/turns",
                    method="POST",
                    body={
                        "input_text": "maybe delivered",
                        "client_message_id": "client-steer-uncertain-api",
                        "async": True,
                        "delivery_policy": "steer_or_queue",
                    },
                    cookie=cookie,
                )

        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "runtime_message_delivery_uncertain")
        self.assertIn("not queued again", payload["detail"])
        self.assertEqual(payload["delivery"], "delivery_uncertain")
        submit.assert_not_called()

    def test_turn_submit_rejects_unknown_delivery_policy_before_queueing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            session = create_runtime_session(
                state.runtime_store,
                session_id="session-policy-api",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                owner_user_id="user:admin",
                governance=state.workspace_store.get_governance("default"),
                platform_allows_full_access=True,
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            with patch("core.api.runtime_api.submit_runtime_turn_async") as submit:
                status, payload, _headers = self._invoke(
                    app,
                    path=f"/api/runtime/sessions/{session.session_id}/turns",
                    method="POST",
                    body={
                        "input_text": "hello",
                        "client_message_id": "client-policy-api",
                        "async": True,
                        "delivery_policy": "unknown",
                    },
                    cookie=cookie,
                )

        self.assertEqual(status, 400)
        self.assertEqual(payload, {"error": "unsupported_delivery_policy"})
        submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
