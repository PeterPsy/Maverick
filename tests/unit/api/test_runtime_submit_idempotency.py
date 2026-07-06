from __future__ import annotations

import tempfile
import time
from threading import Event, Thread
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.identity.service import create_user
from core.runtime.service import create_runtime_session
from core.runtime.turn_submission_service_queue import _queue_turn_with_event
from core.workspaces.service import ensure_workspace_membership
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeSubmitIdempotencyApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def test_prepare_only_session_promotes_on_first_turn(self) -> None:
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
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            with patch("core.api.runtime_api._prewarm_new_runtime_session"):
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body={"agent_id": "chat", "source_app_id": "chat", "prepare_only": True, "title": "New chat"},
                    cookie=cookie,
                )

            self.assertEqual(status, 201)
            session_id = payload["session_id"]
            prepared = state.runtime_store.get_session(session_id)
            self.assertEqual(prepared.thread_visibility, "hidden")
            self.assertEqual(state.runtime_store.list_threads("default"), [])

            def fake_submit_runtime_turn_async(
                submit_state,
                *,
                session,
                input_text,
                client_message_id=None,
                attachments=None,
                app_references=None,
                on_queued=None,
                turn_id=None,
                received_perf_counter=None,
                submission_timing=None,
                **_kwargs,
            ):
                self.assertEqual(session.thread_visibility, "user")
                turn, events = _queue_turn_with_event(
                    submit_state,
                    session=session,
                    input_text=input_text,
                    provider_id="codex",
                    client_message_id=client_message_id,
                    attachments=attachments,
                    app_references=app_references,
                    turn_id=turn_id,
                    received_perf_counter=received_perf_counter,
                    submission_timing=submission_timing,
                )
                if on_queued is not None:
                    on_queued(turn, events)
                return turn, events

            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=fake_submit_runtime_turn_async), patch(
                "core.runtime.turn_submission_service_queue.schedule_runtime_thread_title_generation"
            ):
                turn_status, turn_payload, _headers = self._invoke(
                    app,
                    path=f"/api/runtime/sessions/{session_id}/turns",
                    method="POST",
                    body={"input_text": "hello prepared", "client_message_id": "client-prepared", "async": True},
                    cookie=cookie,
                )

            self.assertEqual(turn_status, 202)
            promoted = state.runtime_store.get_session(session_id)
            self.assertEqual(promoted.thread_visibility, "user")
            self.assertEqual(turn_payload["session"]["thread_visibility"], "user")
            self.assertEqual(turn_payload["thread"]["runtime_session_id"], session_id)
            self.assertEqual(turn_payload["turn"]["client_message_id"], "client-prepared")
            self.assertEqual(len(state.runtime_store.list_threads("default")), 1)

    def test_existing_session_turn_submit_requires_owner_admin_or_grant(self) -> None:
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
            create_runtime_session(
                state.runtime_store,
                session_id="owner-session",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                owner_user_id="user:admin",
                governance=state.workspace_store.get_governance("default"),
                platform_allows_full_access=True,
                start_path=repo_root,
            )
            create_user(state.identity_store, username="member", password="memberpass", platform_role="member")
            ensure_workspace_membership(
                state.workspace_store,
                membership_id="default:user:member",
                workspace_id="default",
                user_id="user:member",
                role="member",
            )
            app = PlatformHost(state, start_path=repo_root)
            member_cookie = self._login(app, username="member", password="memberpass")

            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=AssertionError("submit should be forbidden")):
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions/owner-session/turns",
                    method="POST",
                    body={"input_text": "not my session", "client_message_id": "client-forbidden", "async": True},
                    cookie=member_cookie,
                )

        self.assertEqual(status, 403)
        self.assertEqual(payload, {"error": "runtime_session_turn_submit_forbidden"})

    def test_new_session_turn_retry_reuses_existing_client_message_id(self) -> None:
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
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            calls = 0

            def fake_submit_runtime_turn_async(
                submit_state,
                *,
                session,
                input_text,
                client_message_id=None,
                attachments=None,
                app_references=None,
                on_queued=None,
                turn_id=None,
                received_perf_counter=None,
                submission_timing=None,
                **_kwargs,
            ):
                nonlocal calls
                calls += 1
                turn, events = _queue_turn_with_event(
                    submit_state,
                    session=session,
                    input_text=input_text,
                    provider_id="codex",
                    client_message_id=client_message_id,
                    attachments=attachments,
                    app_references=app_references,
                    turn_id=turn_id,
                    received_perf_counter=received_perf_counter,
                    submission_timing=submission_timing,
                )
                if on_queued is not None:
                    on_queued(turn, events)
                return turn, events

            body = {
                "agent_id": "chat",
                "source_app_id": "chat",
                "input_text": "retry once",
                "client_message_id": "client-retry",
                "async": True,
            }
            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=fake_submit_runtime_turn_async), patch(
                "core.runtime.turn_submission_service_queue.schedule_runtime_thread_title_generation"
            ):
                first_status, first_payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body=body,
                    cookie=cookie,
                )
                second_status, second_payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body=body,
                    cookie=cookie,
                )

            self.assertEqual(first_status, 202)
            self.assertEqual(second_status, 200)
            self.assertEqual(calls, 1)
            self.assertEqual(first_payload["session"]["session_id"], second_payload["session"]["session_id"])
            self.assertEqual(first_payload["turn"]["turn_id"], second_payload["turn"]["turn_id"])
            self.assertEqual(first_payload["turn"]["client_message_id"], "client-retry")
            self.assertEqual(len(state.runtime_store.list_sessions("default")), 1)
            metric_events = [
                event
                for event in state.runtime_store.list_events(first_payload["session"]["session_id"])
                if event.event_type == "runtime.turn.receive_to_queued"
            ]
            self.assertEqual(len(metric_events), 1)
            metric_payload = metric_events[0].payload
            self.assertGreaterEqual(metric_payload["receive_to_queued_ms"], 0)
            for metric_name in ("claim_ms", "session_create_ms", "reference_validate_ms", "queue_turn_ms"):
                self.assertGreaterEqual(metric_payload[metric_name], 0)
            post_queue_events = [
                event
                for event in state.runtime_store.list_events(first_payload["session"]["session_id"])
                if event.event_type == "runtime.turn.post_queue_response"
            ]
            self.assertEqual(len(post_queue_events), 1)
            self.assertGreaterEqual(post_queue_events[0].payload["post_queue_response_ms"], 0)

    def test_new_session_turn_concurrent_retry_reuses_claimed_turn(self) -> None:
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
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            calls = 0
            first_submit_entered = Event()
            release_queue = Event()

            def fake_submit_runtime_turn_async(
                submit_state,
                *,
                session,
                input_text,
                client_message_id=None,
                attachments=None,
                app_references=None,
                on_queued=None,
                turn_id=None,
                received_perf_counter=None,
                submission_timing=None,
                **_kwargs,
            ):
                nonlocal calls
                calls += 1
                first_submit_entered.set()
                self.assertTrue(release_queue.wait(2), "test did not release queue")
                turn, events = _queue_turn_with_event(
                    submit_state,
                    session=session,
                    input_text=input_text,
                    provider_id="codex",
                    client_message_id=client_message_id,
                    attachments=attachments,
                    app_references=app_references,
                    turn_id=turn_id,
                    received_perf_counter=received_perf_counter,
                    submission_timing=submission_timing,
                )
                if on_queued is not None:
                    on_queued(turn, events)
                return turn, events

            body = {
                "agent_id": "chat",
                "source_app_id": "chat",
                "input_text": "retry concurrently",
                "client_message_id": "client-concurrent-retry",
                "async": True,
            }
            results: list[tuple[int, dict] | None] = [None, None]
            errors: list[BaseException] = []

            def invoke(index: int) -> None:
                try:
                    status, payload, _headers = self._invoke(
                        app,
                        path="/api/runtime/sessions",
                        method="POST",
                        body=body,
                        cookie=cookie,
                    )
                    results[index] = (status, payload)
                except BaseException as error:
                    errors.append(error)

            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=fake_submit_runtime_turn_async), patch(
                "core.runtime.turn_submission_service_queue.schedule_runtime_thread_title_generation"
            ):
                first = Thread(target=invoke, args=(0,))
                second = Thread(target=invoke, args=(1,))
                first.start()
                self.assertTrue(first_submit_entered.wait(2), "first submit did not enter queue")
                second.start()
                time.sleep(0.05)
                release_queue.set()
                first.join(2)
                second.join(2)

            if errors:
                raise errors[0]
            self.assertTrue(all(result is not None for result in results))
            first_result = results[0]
            second_result = results[1]
            assert first_result is not None
            assert second_result is not None
            self.assertEqual(first_result[0], 202)
            self.assertEqual(second_result[0], 200)
            self.assertEqual(calls, 1)
            self.assertEqual(first_result[1]["session"]["session_id"], second_result[1]["session"]["session_id"])
            self.assertEqual(first_result[1]["turn"]["turn_id"], second_result[1]["turn"]["turn_id"])
            self.assertEqual(len(state.runtime_store.list_sessions("default")), 1)

    def test_new_session_turn_releases_claim_after_pre_queue_internal_error(self) -> None:
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
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            calls = 0

            def fake_submit_runtime_turn_async(
                submit_state,
                *,
                session,
                input_text,
                client_message_id=None,
                attachments=None,
                app_references=None,
                on_queued=None,
                turn_id=None,
                received_perf_counter=None,
                submission_timing=None,
                **_kwargs,
            ):
                nonlocal calls
                calls += 1
                turn, events = _queue_turn_with_event(
                    submit_state,
                    session=session,
                    input_text=input_text,
                    provider_id="codex",
                    client_message_id=client_message_id,
                    attachments=attachments,
                    app_references=app_references,
                    turn_id=turn_id,
                    received_perf_counter=received_perf_counter,
                    submission_timing=submission_timing,
                )
                if on_queued is not None:
                    on_queued(turn, events)
                return turn, events

            body = {
                "agent_id": "chat",
                "source_app_id": "chat",
                "input_text": "retry after validation crash",
                "client_message_id": "client-validation-crash",
                "async": True,
                "app_references": [{"type": "app", "app_id": "records"}],
            }
            with patch(
                "core.api.runtime_api.validate_runtime_app_references",
                side_effect=RuntimeError("reference validation failed"),
            ), patch("core.api.platform_host.logger"):
                first_status, first_payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body=body,
                    cookie=cookie,
                )
            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=fake_submit_runtime_turn_async), patch(
                "core.runtime.turn_submission_service_queue.schedule_runtime_thread_title_generation"
            ):
                retry_status, retry_payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body=body,
                    cookie=cookie,
                )

            self.assertEqual(first_status, 500)
            self.assertEqual(first_payload, {"error": "internal_server_error"})
            self.assertEqual(retry_status, 202)
            self.assertEqual(calls, 1)
            self.assertEqual(retry_payload["turn"]["client_message_id"], "client-validation-crash")
            self.assertNotIn("idempotency", retry_payload)


if __name__ == "__main__":
    unittest.main()
