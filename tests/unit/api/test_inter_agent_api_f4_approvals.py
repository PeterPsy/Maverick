from __future__ import annotations

from datetime import UTC, datetime, timedelta
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.identity.service import create_user
from core.inter_agent.models import ApprovalRequestRecord
from core.workspaces.service import ensure_workspace_membership
from tests.unit.api.inter_agent_api_f4_support import InterAgentApiF4Fixture, run_payload_without_snapshot


class InterAgentApiF4ApprovalTestCase(InterAgentApiF4Fixture, unittest.TestCase):
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
                body=run_payload_without_snapshot(run_id="run-approval-api"),
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
                body=run_payload_without_snapshot(run_id="run-approval-policy"),
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
