from __future__ import annotations

from datetime import UTC, datetime
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.runtime_threads import create_runtime_thread
from core.runtime.service import create_runtime_session, queue_runtime_turn
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeThreadVisibilityApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def _create_thread_for_session(self, state, session, *, title: str = "New chat"):
        return create_runtime_thread(
            state.runtime_store,
            workspace_id=session.workspace_id,
            thread_id=session.session_id,
            runtime_session_id=session.session_id,
            title=title,
            agent_label=session.agent_id,
            agent_type_id=session.agent_type_id,
            agent_role_id=session.agent_role_id,
            source_app_id=session.source_app_id or session.agent_id,
            system_prompt=session.system_prompt or "",
            project_id=session.project_id,
            now=session.updated_at,
        )

    def _insert_corrupt_session(self, state, repo_root, *, session_id: str = "corrupt-session") -> datetime:
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        state.runtime_store.collections.sessions.update_one(
            {"workspace_id": "default", "session_id": session_id},
            {
                "$set": {
                    "workspace_id": "default",
                    "agent_id": "chat",
                    "status": "running",
                    "requested_mode": None,
                    "effective_mode": "sandbox",
                    "workspace_root": str(repo_root / "workspaces" / "default"),
                    "workdir": str(repo_root / "workspaces" / "default"),
                    "runtime_root": str(
                        repo_root / "workspaces" / "default" / "runtime" / "sessions" / session_id
                    ),
                    "started_at": now,
                    "updated_at": now,
                    "ended_at": None,
                    "last_progress_at": now,
                    "session_kind": "chat_root",
                    "thread_visibility": "not-hidden",
                }
            },
            upsert=True,
        )
        return now

    def _corrupt_session_visibility(self, state, *, session_id: str = "corrupt-session") -> None:
        state.runtime_store.collections.sessions.update_one(
            {"workspace_id": "default", "session_id": session_id},
            {"$set": {"thread_visibility": "not-hidden"}},
        )

    def test_hidden_runtime_session_cannot_be_opened_as_chat_thread(self) -> None:
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
            visible_session = create_runtime_session(
                state.runtime_store,
                session_id="visible-session",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                start_path=repo_root,
            )
            self._create_thread_for_session(state, visible_session)
            create_runtime_session(
                state.runtime_store,
                session_id="hidden-session",
                workspace_id="default",
                agent_id="child-agent",
                source_app_id="chat",
                session_kind="inter_agent_participant",
                thread_visibility="hidden",
                start_path=repo_root,
            )
            queue_runtime_turn(
                state.runtime_store,
                turn_id="hidden-turn",
                session_id="hidden-session",
                input_text="hidden work",
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, create_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads",
                method="POST",
                body={"runtime_session_id": "hidden-session"},
                cookie=cookie,
            )
            open_status, open_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads/hidden-session",
                cookie=cookie,
            )
            read_status, read_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads/hidden-session/read",
                method="POST",
                cookie=cookie,
            )
            list_status, list_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads",
                cookie=cookie,
            )
            patch_status, patch_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads/visible-session",
                method="PATCH",
                body={"runtime_session_id": "hidden-session"},
                cookie=cookie,
            )
            raw_list_status, raw_list_payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions",
                cookie=cookie,
            )
            raw_get_status, raw_get_payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions/hidden-session",
                cookie=cookie,
            )
            raw_events_status, raw_events_payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions/hidden-session/events",
                cookie=cookie,
            )
            raw_turns_status, raw_turns_payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions/hidden-session/turns",
                cookie=cookie,
            )
            raw_post_turn_status, raw_post_turn_payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions/hidden-session/turns",
                method="POST",
                body={"input_text": "direct hidden"},
                cookie=cookie,
            )
            raw_cleanup_status, raw_cleanup_payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions/hidden-session/cleanup",
                method="POST",
                body={"reason": "direct-hidden-cleanup"},
                cookie=cookie,
            )
            turn_get_status, turn_get_payload, _headers = self._invoke(
                app,
                path="/api/runtime/turns/hidden-turn",
                cookie=cookie,
            )
            turn_interrupt_status, turn_interrupt_payload, _headers = self._invoke(
                app,
                path="/api/runtime/turns/hidden-turn/interrupt",
                method="POST",
                body={},
                cookie=cookie,
            )

        self.assertEqual(create_status, 409)
        self.assertEqual(create_payload["error"], "runtime_session_hidden")
        self.assertEqual(open_status, 409)
        self.assertEqual(open_payload["error"], "runtime_session_hidden")
        self.assertEqual(read_status, 409)
        self.assertEqual(read_payload["error"], "runtime_session_hidden")
        self.assertEqual(list_status, 200)
        self.assertEqual([thread["runtime_session_id"] for thread in list_payload["threads"]], ["visible-session"])
        self.assertEqual(patch_status, 409)
        self.assertEqual(patch_payload["error"], "runtime_session_hidden")
        self.assertEqual(raw_list_status, 200)
        self.assertEqual([session["session_id"] for session in raw_list_payload["items"]], ["visible-session"])
        for status, payload in [
            (raw_get_status, raw_get_payload),
            (raw_events_status, raw_events_payload),
            (raw_turns_status, raw_turns_payload),
            (raw_post_turn_status, raw_post_turn_payload),
            (raw_cleanup_status, raw_cleanup_payload),
            (turn_get_status, turn_get_payload),
            (turn_interrupt_status, turn_interrupt_payload),
        ]:
            self.assertEqual(status, 409)
            self.assertEqual(payload["error"], "runtime_session_hidden")

    def test_invalid_runtime_session_visibility_is_not_exposed_as_chat_thread(self) -> None:
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
            visible_session = create_runtime_session(
                state.runtime_store,
                session_id="visible-session",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                start_path=repo_root,
            )
            self._create_thread_for_session(state, visible_session)
            now = self._insert_corrupt_session(state, repo_root)
            state.runtime_store.save_thread(
                RuntimeThreadRecord(
                    thread_id="stale-corrupt",
                    workspace_id="default",
                    runtime_session_id="corrupt-session",
                    title="Corrupt",
                    agent_label="chat",
                    agent_type_id="",
                    agent_role_id="",
                    source_app_id="chat",
                    system_prompt="",
                    project_id=None,
                    archived=False,
                    availability="free",
                    created_at=now,
                    updated_at=now,
                )
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, create_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads",
                method="POST",
                body={"runtime_session_id": "corrupt-session"},
                cookie=cookie,
            )
            list_status, list_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads",
                cookie=cookie,
            )

        self.assertEqual(create_status, 409)
        self.assertEqual(create_payload["error"], "runtime_session_hidden")
        self.assertEqual(create_payload["thread_visibility"], "invalid")
        self.assertEqual(list_status, 200)
        self.assertEqual([thread["runtime_session_id"] for thread in list_payload["threads"]], ["visible-session"])

    def test_runtime_thread_rest_catalog_uses_summary_payload_without_duplicate_items(self) -> None:
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
            for index in range(55):
                session = create_runtime_session(
                    state.runtime_store,
                    session_id=f"visible-session-{index:02d}",
                    workspace_id="default",
                    agent_id="chat",
                    source_app_id="chat",
                    system_prompt=f"Long private prompt {index:02d} " + ("x" * 2000),
                    thread_title=f"Archive thread {index:02d}",
                    start_path=repo_root,
                )
                create_runtime_thread(
                    state.runtime_store,
                    workspace_id="default",
                    thread_id=session.session_id,
                    runtime_session_id=session.session_id,
                    title=f"Archive thread {index:02d}",
                    agent_label="chat",
                    source_app_id="chat",
                    system_prompt=session.system_prompt or "",
                    now=session.updated_at,
                )

            def fail_list_turns(_session_id: str):
                raise AssertionError("REST thread catalogs must not scan runtime turns")

            state.runtime_store.list_turns = fail_list_turns  # type: ignore[method-assign]
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            list_status, list_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads",
                cookie=cookie,
            )
            next_status, next_payload, _headers = self._invoke(
                app,
                path=f"/api/runtime/threads?cursor={list_payload['threads_page']['cursor']}",
                cookie=cookie,
            )
            missing_cursor_status, missing_cursor_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads?cursor=missing-thread",
                cookie=cookie,
            )
            search_status, search_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads?query=visible-session-00",
                cookie=cookie,
            )
            detail_status, detail_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads/visible-session-00",
                cookie=cookie,
            )

        self.assertEqual(list_status, 200)
        self.assertEqual(list_payload["workspace_id"], "default")
        self.assertEqual(len(list_payload["threads"]), 50)
        self.assertNotIn("items", list_payload["threads_page"])
        self.assertEqual(list_payload["threads_page"]["limit"], 50)
        self.assertTrue(list_payload["threads_page"]["has_more"])
        self.assertIsNotNone(list_payload["threads_page"]["cursor"])
        self.assertEqual(list_payload["threads_page"]["sort"], "recency_desc")
        self.assertTrue(list_payload["threads_page"]["cursor_found"])
        self.assertEqual(list_payload["threads_page"]["total"], 55)
        self.assertEqual(list_payload["threads_page"]["filtered_total"], 55)
        self.assertTrue(all("system_prompt" not in thread for thread in list_payload["threads"]))
        self.assertTrue(all("provider_id" not in thread for thread in list_payload["threads"]))
        self.assertTrue(all("title_generation_input_hash" not in thread for thread in list_payload["threads"]))
        self.assertEqual(next_status, 200)
        self.assertEqual(len(next_payload["threads"]), 5)
        self.assertNotIn("items", next_payload["threads_page"])
        self.assertFalse(next_payload["threads_page"]["has_more"])
        self.assertIsNone(next_payload["threads_page"]["cursor"])
        self.assertTrue(next_payload["threads_page"]["cursor_found"])
        self.assertFalse(
            {thread["thread_id"] for thread in list_payload["threads"]}.intersection(
                thread["thread_id"] for thread in next_payload["threads"]
            )
        )
        self.assertEqual(missing_cursor_status, 200)
        self.assertEqual(missing_cursor_payload["threads"], [])
        self.assertFalse(missing_cursor_payload["threads_page"]["has_more"])
        self.assertFalse(missing_cursor_payload["threads_page"]["cursor_found"])
        self.assertEqual(search_status, 200)
        self.assertEqual([thread["runtime_session_id"] for thread in search_payload["threads"]], ["visible-session-00"])
        self.assertEqual(search_payload["threads_page"]["query"], "visible-session-00")
        self.assertEqual(detail_status, 200)
        self.assertIn("system_prompt", detail_payload["thread"])
        self.assertTrue(detail_payload["thread"]["system_prompt"].startswith("Long private prompt 00"))

    def test_invalid_runtime_session_visibility_is_controlled_for_raw_session_api(self) -> None:
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
            self._insert_corrupt_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            session_status, session_payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions/corrupt-session",
                cookie=cookie,
            )
            events_status, events_payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions/corrupt-session/events",
                cookie=cookie,
            )
            turns_status, turns_payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions/corrupt-session/turns",
                cookie=cookie,
            )
            post_turn_status, post_turn_payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions/corrupt-session/turns",
                method="POST",
                body={"input_text": "hello"},
                cookie=cookie,
            )

        self.assertEqual(session_status, 404)
        self.assertEqual(session_payload["error"], "runtime_session_not_found")
        self.assertEqual(events_status, 404)
        self.assertEqual(events_payload["error"], "runtime_session_not_found")
        self.assertEqual(turns_status, 404)
        self.assertEqual(turns_payload["error"], "runtime_session_not_found")
        self.assertEqual(post_turn_status, 404)
        self.assertEqual(post_turn_payload["error"], "runtime_session_not_found")

    def test_interrupt_turn_with_invalid_runtime_session_visibility_is_controlled(self) -> None:
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
                session_id="corrupt-session",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                start_path=repo_root,
            )
            queue_runtime_turn(
                state.runtime_store,
                turn_id="turn-corrupt",
                session_id="corrupt-session",
                input_text="hello",
            )
            self._corrupt_session_visibility(state)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            interrupt_status, interrupt_payload, _headers = self._invoke(
                app,
                path="/api/runtime/turns/turn-corrupt/interrupt",
                method="POST",
                body={},
                cookie=cookie,
            )

        self.assertEqual(interrupt_status, 404)
        self.assertEqual(interrupt_payload["error"], "runtime_turn_not_found")


if __name__ == "__main__":
    unittest.main()
