from __future__ import annotations

from datetime import UTC, datetime
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.service import create_runtime_session
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeThreadVisibilityApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
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
            create_runtime_session(
                state.runtime_store,
                session_id="visible-session",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                start_path=repo_root,
            )
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
            create_runtime_session(
                state.runtime_store,
                session_id="visible-session",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                start_path=repo_root,
            )
            now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
            state.runtime_store.collections.sessions.update_one(
                {"session_id": "corrupt-session"},
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
                            repo_root / "workspaces" / "default" / "runtime" / "sessions" / "corrupt-session"
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


if __name__ == "__main__":
    unittest.main()
