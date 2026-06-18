from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.identity.service import create_user
from core.inter_agent.service import InterAgentService
from core.runtime.runtime_session import RuntimeSessionGrantRecord
from core.runtime.service import create_runtime_session
from core.workspaces.service import ensure_workspace_membership
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport
from tests.unit.api.test_inter_agent_api import _run_payload_without_snapshot


class InterAgentApiAuthorizationTestCase(AppReferenceApiTestSupport, unittest.TestCase):
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

    def _create_root_session(self, state, repo_root) -> None:
        create_runtime_session(
            state.runtime_store,
            session_id="root-session",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            governance=state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )

    def test_run_detail_and_events_require_owner_admin_or_grant(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            create_user(state.identity_store, username="member", password="memberpass", platform_role="member")
            ensure_workspace_membership(
                state.workspace_store,
                membership_id="default:user:member",
                workspace_id="default",
                user_id="user:member",
                role="member",
            )
            app = PlatformHost(state, start_path=repo_root)
            admin_cookie = self._login(app)
            member_cookie = self._login(app, username="member", password="memberpass")

            create_status, _payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body={**_run_payload_without_snapshot(run_id="run-api-auth"), "visibility_level": "detail"},
                cookie=admin_cookie,
            )
            run = state.inter_agent_store.get_run("run-api-auth", workspace_id="default")
            service = InterAgentService(state.inter_agent_store)
            service.record_event(
                run,
                event_type="inter_agent.task.completed",
                participant_id="researcher",
                visibility_plane="detail",
                payload={"summary": "safe detail", "output_text": "detail output"},
                correlation_id="detail-event",
                idempotency_key="run-api-auth:detail-event",
            )
            service.record_event(
                run,
                event_type="inter_agent.task.completed",
                participant_id="researcher",
                visibility_plane="debug",
                payload={"summary": "debug detail"},
                correlation_id="debug-event",
                idempotency_key="run-api-auth:debug-event",
            )

            list_status, list_payload, _headers = self._invoke(app, path="/api/inter-agent/runs", cookie=member_cookie)
            detail_status, detail_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-auth",
                cookie=member_cookie,
            )
            events_status, events_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-auth/events?visibility_plane=detail",
                cookie=member_cookie,
            )
            root = state.runtime_store.get_session("root-session")
            state.runtime_store.save_session(
                replace(
                    root,
                    grants=[
                        RuntimeSessionGrantRecord(
                            operation="inter_agent_root",
                            grantee_kind="user",
                            grantee_id="user:member",
                            issued_by_user_id="user:admin",
                        )
                    ],
                )
            )
            granted_status, granted_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs/run-api-auth/events?visibility_plane=debug",
                cookie=member_cookie,
            )

        self.assertEqual(create_status, 201)
        self.assertEqual(list_status, 200)
        self.assertEqual(list_payload["items"], [])
        self.assertEqual(detail_status, 403)
        self.assertEqual(detail_payload["error"], "inter_agent_run_view_forbidden")
        self.assertEqual(events_status, 403)
        self.assertEqual(events_payload["error"], "inter_agent_run_view_forbidden")
        self.assertEqual(granted_status, 200)
        self.assertEqual(granted_payload["visibility_plane"], "detail")
        self.assertIn("detail output", [item["payload"].get("output_text") for item in granted_payload["items"]])
        self.assertNotIn("debug detail", [item["payload"].get("summary") for item in granted_payload["items"]])


if __name__ == "__main__":
    unittest.main()
