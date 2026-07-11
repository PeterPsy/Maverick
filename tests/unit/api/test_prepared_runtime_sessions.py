from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.api.app_reference_payloads import (
    clear_runtime_app_reference_materialization_cache,
    runtime_app_reference_materialization_cache_stats,
)
from core.apps.service import install_store_app, register_app_source_from_contract
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import queue_runtime_turn
from core.runtime.turn_submission_service_queue import _queue_turn_with_event
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class PreparedRuntimeSessionsApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def setUp(self) -> None:
        clear_runtime_app_reference_materialization_cache()

    def test_prepare_only_session_promotes_on_first_turn_with_draft_metadata(self) -> None:
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
                    body={
                        "agent_id": "chat",
                        "source_app_id": "chat",
                        "prepare_only": True,
                        "title": "New chat",
                        "agent_label": "Catalog Agent",
                        "agent_type_id": "agent-type-1",
                        "agent_role_id": "role-1",
                        "project_id": "proj-1",
                    },
                    cookie=cookie,
                )

            self.assertEqual(status, 201)
            session_id = payload["session_id"]
            prepared = state.runtime_store.get_session(session_id)
            self.assertEqual(prepared.thread_visibility, "hidden")
            self.assertEqual(prepared.agent_label, "Catalog Agent")
            self.assertEqual(prepared.agent_type_id, "agent-type-1")
            self.assertEqual(prepared.agent_role_id, "role-1")
            self.assertEqual(prepared.project_id, "proj-1")
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
            self.assertEqual(turn_payload["thread"]["agent_label"], "Catalog Agent")
            self.assertEqual(turn_payload["thread"]["agent_type_id"], "agent-type-1")
            self.assertEqual(turn_payload["thread"]["agent_role_id"], "role-1")
            self.assertEqual(turn_payload["thread"]["project_id"], "proj-1")
            self.assertEqual(turn_payload["turn"]["client_message_id"], "client-prepared")
            threads = state.runtime_store.list_threads("default")
            self.assertEqual(len(threads), 1)
            self.assertEqual(threads[0].project_id, "proj-1")

    def test_hidden_prepared_session_with_accepted_turn_is_recovered_as_visible_thread(self) -> None:
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
            session = state.runtime_store.get_session(session_id)
            self.assertEqual(session.thread_visibility, "hidden")
            turn = queue_runtime_turn(
                state.runtime_store,
                turn_id="accepted-hidden-turn",
                session_id=session_id,
                input_text="accepted while hidden",
            )
            state.runtime_store.save_thread(
                RuntimeThreadRecord(
                    thread_id=session_id,
                    workspace_id="default",
                    runtime_session_id=session_id,
                    title="New chat",
                    agent_label="chat",
                    agent_type_id="",
                    agent_role_id="",
                    source_app_id="chat",
                    system_prompt="",
                    project_id=None,
                    archived=False,
                    availability="queued",
                    created_at=session.started_at or session.updated_at,
                    updated_at=turn.created_at,
                    last_user_message_at=turn.created_at,
                    last_completed_response_at=None,
                    last_completed_turn_id=None,
                    completed_response_read_at_by_user_id={},
                    title_pending=True,
                    title_source="pending",
                    title_generation_input_hash="hash",
                    title_generation_failure=None,
                    title_generation_provider_id="",
                    title_generation_model_id="",
                )
            )

            list_status, list_payload, _headers = self._invoke(app, path="/api/runtime/threads", cookie=cookie)
            events_status, events_payload, _headers = self._invoke(
                app,
                path=f"/api/runtime/sessions/{session_id}/events",
                cookie=cookie,
            )
            interrupt_status, interrupt_payload, _headers = self._invoke(
                app,
                path=f"/api/runtime/turns/{turn.turn_id}/interrupt",
                method="POST",
                body={},
                cookie=cookie,
            )

            self.assertEqual(list_status, 200)
            self.assertEqual([thread["runtime_session_id"] for thread in list_payload["threads"]], [session_id])
            self.assertEqual(events_status, 200)
            self.assertIn("items", events_payload)
            self.assertEqual(interrupt_status, 200)
            self.assertTrue(interrupt_payload["interrupted"])
            self.assertEqual(state.runtime_store.get_session(session_id).thread_visibility, "user")
            self.assertEqual(state.runtime_store.get_turn(turn.turn_id).status, "cancelled")

    def test_prepare_only_app_references_are_cached_for_first_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_reference_app(repo_root / "apps" / "records")
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            source = register_app_source_from_contract(
                state.app_store,
                source_kind="platform",
                source_path=str(repo_root / "apps" / "records"),
            )
            install_store_app(state.app_store, source_id=source.source_id, workspace_id="default", start_path=repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            with patch("core.api.runtime_api._prewarm_new_runtime_session"):
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body={"agent_id": "chat", "source_app_id": "chat", "prepare_only": True},
                    cookie=cookie,
                )

            self.assertEqual(status, 201)
            session_id = payload["session_id"]
            app_references = [
                {"type": "entity", "app_id": "records", "entity_type": "record", "entity_id": "record-1"},
            ]
            prepare_status, prepare_payload, _headers = self._invoke(
                app,
                path=f"/api/runtime/sessions/{session_id}/app-references/prepare",
                method="POST",
                body={"app_references": app_references},
                cookie=cookie,
            )
            second_prepare_status, second_prepare_payload, _headers = self._invoke(
                app,
                path=f"/api/runtime/sessions/{session_id}/app-references/prepare",
                method="POST",
                body={"app_references": app_references},
                cookie=cookie,
            )
            changed_fingerprint_references = [
                {
                    "type": "entity",
                    "app_id": "records",
                    "entity_type": "record",
                    "entity_id": "record-1",
                    "metadata": {"sha256": "changed"},
                },
            ]
            changed_prepare_status, changed_prepare_payload, _headers = self._invoke(
                app,
                path=f"/api/runtime/sessions/{session_id}/app-references/prepare",
                method="POST",
                body={"app_references": changed_fingerprint_references},
                cookie=cookie,
            )
            captured: dict[str, object] = {}

            def fake_submit_runtime_turn_async(
                _submit_state,
                *,
                session,
                input_text,
                app_references=None,
                app_reference_materializer=None,
                **_kwargs,
            ):
                if callable(app_reference_materializer):
                    materialized = app_reference_materializer(app_references or [])
                    captured["reference_cache_hit"] = getattr(materialized, "reference_cache_hit", False)
                    captured["materialized_app_references"] = getattr(materialized, "references", materialized)
                now = datetime.now(tz=UTC)
                return RuntimeTurnRecord(
                    turn_id="turn-prepared-refs",
                    session_id=session.session_id,
                    workspace_id=session.workspace_id,
                    status="queued",
                    input_text=input_text,
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    completed_at=None,
                    failure_reason=None,
                ), []

            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=fake_submit_runtime_turn_async):
                turn_status, _turn_payload, _headers = self._invoke(
                    app,
                    path=f"/api/runtime/sessions/{session_id}/turns",
                    method="POST",
                    body={
                        "input_text": "Review @Launch record [ref:records/record/record-1]",
                        "client_message_id": "client-prepared-refs",
                        "app_references": app_references,
                        "async": True,
                    },
                    cookie=cookie,
                )

            self.assertEqual(prepare_status, 200)
            self.assertEqual(prepare_payload["status"], "ready")
            self.assertEqual(prepare_payload["reference_count"], 1)
            self.assertEqual(prepare_payload["materialized_reference_count"], 1)
            self.assertFalse(prepare_payload["reference_cache_hit"])
            self.assertEqual(second_prepare_status, 200)
            self.assertTrue(second_prepare_payload["reference_cache_hit"])
            self.assertEqual(second_prepare_payload["reference_fingerprint"], prepare_payload["reference_fingerprint"])
            self.assertEqual(changed_prepare_status, 200)
            self.assertFalse(changed_prepare_payload["reference_cache_hit"])
            self.assertNotEqual(changed_prepare_payload["reference_fingerprint"], prepare_payload["reference_fingerprint"])
            self.assertEqual(turn_status, 202)
            self.assertTrue(captured["reference_cache_hit"])
            self.assertEqual(captured["materialized_app_references"][0]["label"], "Launch record")

    def test_prepare_only_app_reference_cache_is_bounded_and_reports_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_reference_app(repo_root / "apps" / "records")
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            source = register_app_source_from_contract(
                state.app_store,
                source_kind="platform",
                source_path=str(repo_root / "apps" / "records"),
            )
            install_store_app(state.app_store, source_id=source.source_id, workspace_id="default", start_path=repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            app_references = [
                {"type": "entity", "app_id": "records", "entity_type": "record", "entity_id": "record-1"},
            ]

            with patch("core.api.runtime_api._prewarm_new_runtime_session"), patch(
                "core.api.app_reference_payloads.RUNTIME_APP_REFERENCE_CACHE_MAX_ENTRIES",
                2,
            ):
                for index in range(3):
                    session_status, session_payload, _headers = self._invoke(
                        app,
                        path="/api/runtime/sessions",
                        method="POST",
                        body={"agent_id": "chat", "source_app_id": "chat", "prepare_only": True},
                        cookie=cookie,
                    )
                    self.assertEqual(session_status, 201)
                    prepare_status, prepare_payload, _headers = self._invoke(
                        app,
                        path=f"/api/runtime/sessions/{session_payload['session_id']}/app-references/prepare",
                        method="POST",
                        body={"app_references": app_references},
                        cookie=cookie,
                    )
                    self.assertEqual(prepare_status, 200)
                    self.assertEqual(prepare_payload["status"], "ready")
                    self.assertFalse(prepare_payload["reference_cache_hit"], f"unexpected cache hit on insert {index}")

                stats = runtime_app_reference_materialization_cache_stats()

            metrics = state.observability_store.list_metrics(workspace_id="default")
            cache_size_metrics = [metric for metric in metrics if metric.metric_name == "reference_cache_size"]
            cache_eviction_metrics = [metric for metric in metrics if metric.metric_name == "reference_cache_evictions"]
            self.assertEqual(stats.size, 2)
            self.assertEqual(stats.max_entries, 2)
            self.assertEqual(stats.evictions, 1)
            self.assertEqual(cache_size_metrics[-1].value, 2)
            self.assertEqual(sum(metric.value for metric in cache_eviction_metrics), 1)

    def test_invalid_prepare_only_first_turn_keeps_session_hidden_without_thread(self) -> None:
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
                    body={"agent_id": "chat", "source_app_id": "chat", "prepare_only": True},
                    cookie=cookie,
                )

            self.assertEqual(status, 201)
            session_id = payload["session_id"]

            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=AssertionError("invalid submit should not queue")):
                turn_status, turn_payload, _headers = self._invoke(
                    app,
                    path=f"/api/runtime/sessions/{session_id}/turns",
                    method="POST",
                    body={
                        "input_text": "bad routing",
                        "client_message_id": "client-invalid-routing",
                        "routing_profile": "bad",
                        "async": True,
                    },
                    cookie=cookie,
                )

            self.assertEqual(turn_status, 400)
            self.assertEqual(turn_payload, {"error": "unsupported_routing_profile"})
            session = state.runtime_store.get_session(session_id)
            self.assertEqual(session.thread_visibility, "hidden")
            self.assertEqual(state.runtime_store.list_threads("default"), [])
            self.assertEqual(state.runtime_store.list_turns(session_id), [])

    def test_prepare_only_ttl_uses_full_runtime_cleanup(self) -> None:
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
                    body={"agent_id": "chat", "source_app_id": "chat", "prepare_only": True},
                    cookie=cookie,
                )

            self.assertEqual(status, 201)
            expired_session_id = payload["session_id"]
            expired = state.runtime_store.get_session(expired_session_id)
            state.runtime_store.save_session(replace(expired, updated_at=datetime.now(tz=UTC) - timedelta(minutes=31)))

            with patch("core.api.runtime_api.cleanup_runtime_session", return_value={"found": True}) as cleanup, patch(
                "core.api.runtime_api._prewarm_new_runtime_session"
            ):
                status, _payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body={"agent_id": "chat", "source_app_id": "chat", "prepare_only": True},
                    cookie=cookie,
                )

            self.assertEqual(status, 201)
            cleanup.assert_called_once()
            self.assertEqual(cleanup.call_args.kwargs["session_id"], expired_session_id)
            self.assertEqual(cleanup.call_args.kwargs["reason"], "prepared_session_expired")
            self.assertFalse(cleanup.call_args.kwargs["publish_thread_events"])
            self.assertTrue(cleanup.call_args.kwargs["allow_hidden_prepared_chat_cleanup"])


if __name__ == "__main__":
    unittest.main()
