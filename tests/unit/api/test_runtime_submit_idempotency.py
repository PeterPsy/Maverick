from __future__ import annotations

from datetime import UTC, datetime
import tempfile
import time
from threading import Event, Thread
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.identity.service import create_user
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.service import create_runtime_session
from core.runtime.turn_submission_service_queue import _queue_turn_with_event
from core.workspaces.service import ensure_workspace_membership
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeSubmitIdempotencyApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def test_existing_session_retry_reuses_predecessor_turn_after_continuation_fork(self) -> None:
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
            predecessor = create_runtime_session(
                state.runtime_store,
                session_id="retry-lineage-predecessor",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                owner_user_id="user:admin",
                governance=state.workspace_store.get_governance("default"),
                platform_allows_full_access=True,
                start_path=repo_root,
            )
            with patch(
                "core.runtime.turn_submission_service_queue.schedule_runtime_thread_title_generation"
            ):
                original_turn, _events = _queue_turn_with_event(
                    state,
                    session=predecessor,
                    input_text="persist once",
                    provider_id="codex",
                    client_message_id="retry-across-fork",
                    attachments=[],
                    app_references=[],
                )
            successor = create_runtime_session(
                state.runtime_store,
                session_id="retry-lineage-successor",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                owner_user_id="user:admin",
                predecessor_session_id=predecessor.session_id,
                lineage_root_session_id=predecessor.session_id,
                continuation_handoff_id="retry-lineage-handoff",
                governance=state.workspace_store.get_governance("default"),
                platform_allows_full_access=True,
                start_path=repo_root,
            )
            state.runtime_store.link_continuation_successor(
                workspace_id="default",
                predecessor_session_id=predecessor.session_id,
                successor_session_id=successor.session_id,
                handoff_id="retry-lineage-handoff",
                now=datetime.now(tz=UTC),
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            with patch(
                "core.api.runtime_api.submit_runtime_turn_async",
                side_effect=AssertionError("lineage retry must not queue"),
            ):
                status, payload, _headers = self._invoke(
                    app,
                    path=f"/api/runtime/sessions/{predecessor.session_id}/turns",
                    method="POST",
                    body={
                        "input_text": "persist once",
                        "client_message_id": "retry-across-fork",
                        "async": True,
                    },
                    cookie=cookie,
                )
            successor_turns = state.runtime_store.list_turns(successor.session_id)

        self.assertEqual(status, 200)
        self.assertEqual(payload["session"]["session_id"], successor.session_id)
        self.assertEqual(payload["turn"]["turn_id"], original_turn.turn_id)
        self.assertEqual(successor_turns, [])

    def test_session_cleanup_via_predecessor_removes_complete_continuation_lineage(self) -> None:
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
            predecessor = create_runtime_session(
                state.runtime_store,
                session_id="cleanup-lineage-predecessor",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                owner_user_id="user:admin",
                governance=state.workspace_store.get_governance("default"),
                platform_allows_full_access=True,
                start_path=repo_root,
            )
            successor = create_runtime_session(
                state.runtime_store,
                session_id="cleanup-lineage-successor",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                owner_user_id="user:admin",
                predecessor_session_id=predecessor.session_id,
                lineage_root_session_id=predecessor.session_id,
                continuation_handoff_id="cleanup-lineage-handoff",
                governance=state.workspace_store.get_governance("default"),
                platform_allows_full_access=True,
                start_path=repo_root,
            )
            state.runtime_store.link_continuation_successor(
                workspace_id="default",
                predecessor_session_id=predecessor.session_id,
                successor_session_id=successor.session_id,
                handoff_id="cleanup-lineage-handoff",
                now=datetime.now(tz=UTC),
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            status, payload, _headers = self._invoke(
                app,
                path=f"/api/runtime/sessions/{predecessor.session_id}/cleanup",
                method="POST",
                body={"reason": "delete logical chat"},
                cookie=cookie,
            )

            for session_id in (predecessor.session_id, successor.session_id):
                with self.assertRaises(RuntimeSessionNotFoundError):
                    state.runtime_store.get_session(session_id)

        self.assertEqual(status, 200)
        lineage_cleanup = payload["continuation_lineage_cleanup"]
        self.assertEqual(lineage_cleanup["requested_session_id"], predecessor.session_id)
        self.assertEqual(lineage_cleanup["resolved_session_id"], successor.session_id)
        self.assertEqual(
            set(lineage_cleanup["cleaned_session_ids"]),
            {predecessor.session_id, successor.session_id},
        )

    def test_existing_agentic_turn_is_rejected_before_queue_when_authority_is_invalid(self) -> None:
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
                session_id="invalid-authority-session",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                owner_user_id="user:admin",
                runtime_mode="agentic",
                governance=state.workspace_store.get_governance("default"),
                platform_allows_full_access=True,
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            with patch(
                "core.api.runtime_api.submit_runtime_turn_async",
                side_effect=AssertionError("turn must not be queued"),
            ):
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions/invalid-authority-session/turns",
                    method="POST",
                    body={
                        "input_text": "do not persist this",
                        "client_message_id": "invalid-authority-message",
                        "async": True,
                    },
                    cookie=cookie,
                )
            persisted_turns = state.runtime_store.list_turns(
                "invalid-authority-session"
            )

        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "runtime_profile_upgrade_required")
        self.assertEqual(payload["admission_status"], "upgrade_required")
        self.assertEqual(
            persisted_turns,
            [],
        )

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

    def test_app_references_prepare_rejects_visible_non_owner_without_turn_submit_authority(self) -> None:
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
            owner_session = create_runtime_session(
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
            self.assertEqual(owner_session.owner_user_id, "user:admin")
            self.assertEqual(
                state.workspace_store.get_membership(user_id="user:member", workspace_id="default").role,
                "member",
            )

            with patch(
                "core.api.runtime_api.validate_runtime_app_references",
                side_effect=AssertionError("prepare should fail before reference validation"),
            ), patch(
                "core.api.runtime_api.materialize_runtime_app_references_with_metrics",
                side_effect=AssertionError("prepare should fail before materialization"),
            ):
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions/owner-session/app-references/prepare",
                    method="POST",
                    body={"app_references": [{"type": "app", "app_id": "records"}]},
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
                "client_submission_started_at": datetime.now(tz=UTC).isoformat(),
                "client_submission_metrics": {
                    "attachment_upload_ms": 0,
                    "attachment_upload_ready_before_submit": True,
                    "attachment_upload_wait_on_submit_ms": 0,
                    "prepare_refs_wait_on_submit_ms": 12.25,
                    "prepared_session_ready_before_submit": False,
                    "prepared_session_wait_on_submit_ms": 0,
                    "submit_post_ms": 123.456,
                    "ignored": "nope",
                },
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
            self.assertGreaterEqual(metric_payload["client_click_to_queued_ms"], 0)
            self.assertEqual(metric_payload["attachment_upload_ms"], 0)
            self.assertEqual(metric_payload["attachment_upload_ready_before_submit"], True)
            self.assertEqual(metric_payload["attachment_upload_wait_on_submit_ms"], 0)
            self.assertEqual(metric_payload["prepare_refs_wait_on_submit_ms"], 12.25)
            self.assertEqual(metric_payload["prepared_session_ready_before_submit"], False)
            self.assertEqual(metric_payload["prepared_session_wait_on_submit_ms"], 0)
            self.assertNotIn("submit_post_ms", metric_payload)
            self.assertNotIn("ignored", metric_payload)
            post_queue_events = [
                event
                for event in state.runtime_store.list_events(first_payload["session"]["session_id"])
                if event.event_type == "runtime.turn.post_queue_response"
            ]
            self.assertEqual(len(post_queue_events), 1)
            self.assertGreaterEqual(post_queue_events[0].payload["post_queue_response_ms"], 0)

            metrics_status, metrics_payload, _headers = self._invoke(
                app,
                path=f"/api/runtime/turns/{first_payload['turn']['turn_id']}/client-metrics",
                method="POST",
                body={"metrics": {"submit_post_ms": 42.25, "prepared_session_ready_before_submit": True}},
                cookie=cookie,
            )
            self.assertEqual(metrics_status, 200)
            self.assertEqual(metrics_payload["metric_count"], 2)
            client_metric_events = [
                event
                for event in state.runtime_store.list_events(first_payload["session"]["session_id"])
                if event.event_type == "runtime.turn.client_submit_metrics"
            ]
            self.assertEqual(len(client_metric_events), 1)
            self.assertEqual(client_metric_events[0].payload["submit_post_ms"], 42.25)
            self.assertEqual(client_metric_events[0].payload["prepared_session_ready_before_submit"], True)

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
