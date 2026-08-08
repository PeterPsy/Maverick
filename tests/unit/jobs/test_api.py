from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.identity.service import create_user
from core.jobs.serialization import job_spec_to_payload
from core.workspaces.service import ensure_workspace_membership
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport
from tests.unit.jobs.support import make_spec


class JobApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def test_authenticated_api_submit_list_get_and_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_root = self._repo_root(temporary_directory)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repository_root, install_builtin_apps=False)
            host = PlatformHost(state, start_path=repository_root)
            cookie = self._login(host)
            actor_id = state.identity_store.list_users()[0].user_id
            spec = _future_spec(actor_id=actor_id)

            status, submitted, _headers = self._invoke(
                host,
                path="/api/jobs",
                method="POST",
                body={"job_id": "job-api", "spec": job_spec_to_payload(spec)},
                cookie=cookie,
            )
            list_status, listed, _headers = self._invoke(
                host,
                path="/api/jobs",
                method="GET",
                cookie=cookie,
            )
            get_status, detail, _headers = self._invoke(
                host,
                path="/api/jobs/job-api?include_history=true",
                method="GET",
                cookie=cookie,
            )
            cancel_status, cancelled, _headers = self._invoke(
                host,
                path="/api/jobs/job-api/cancel",
                method="POST",
                body={"reason": "user request"},
                cookie=cookie,
            )
            force_spec = replace(spec, idempotency_key="idem-force")
            self._invoke(
                host,
                path="/api/jobs",
                method="POST",
                body={"job_id": "job-api-force", "spec": job_spec_to_payload(force_spec)},
                cookie=cookie,
            )
            force_status, force_cancelled, _headers = self._invoke(
                host,
                path="/api/jobs/job-api-force/cancel",
                method="POST",
                body={"reason": "admin request", "force": True},
                cookie=cookie,
            )

        self.assertEqual(status, 201)
        self.assertEqual(submitted["job"]["state"], "queued")
        self.assertEqual(list_status, 200)
        self.assertEqual(listed["jobs"][0]["job_id"], "job-api")
        self.assertEqual(get_status, 200)
        self.assertEqual(detail["events"][0]["state"], "queued")
        self.assertEqual(cancel_status, 200)
        self.assertEqual(cancelled["job"]["state"], "cancelled")
        self.assertEqual(force_status, 200)
        self.assertEqual(force_cancelled["job"]["state"], "cancelled")
        self.assertEqual(submitted["job"]["spec"]["submitted_by_actor_id"], actor_id)

    def test_api_enforces_trusted_actor_and_workspace_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_root = self._repo_root(temporary_directory)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repository_root, install_builtin_apps=False)
            host = PlatformHost(state, start_path=repository_root)
            cookie = self._login(host)
            actor_id = state.identity_store.list_users()[0].user_id
            state.job_service.submit(
                _future_spec(workspace_id="other-workspace", actor_id="other-actor"),
                job_id="other-job",
            )

            list_status, listed, _headers = self._invoke(host, path="/api/jobs", cookie=cookie)
            get_status, _missing, _headers = self._invoke(host, path="/api/jobs/other-job", cookie=cookie)
            submit_status, rejected, _headers = self._invoke(
                host,
                path="/api/jobs",
                method="POST",
                cookie=cookie,
                body={"spec": job_spec_to_payload(_future_spec(actor_id="spoofed-actor"))},
            )

        self.assertEqual(list_status, 200)
        self.assertEqual(listed["jobs"], [])
        self.assertEqual(get_status, 404)
        self.assertEqual(submit_status, 400)
        self.assertIn("trusted actor", rejected["detail"])
        self.assertNotEqual(actor_id, "spoofed-actor")

    def test_api_requires_authentication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_root = self._repo_root(temporary_directory)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repository_root, install_builtin_apps=False)
            status, payload, _headers = self._invoke(
                PlatformHost(state, start_path=repository_root),
                path="/api/jobs",
                method="GET",
            )

        self.assertEqual(status, 401)
        self.assertEqual(payload, {"error": "authentication_required"})

    def test_api_rejects_forced_cancel_from_non_admin_member(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_root = self._repo_root(temporary_directory)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repository_root, install_builtin_apps=False)
            create_user(
                state.identity_store,
                username="member",
                password="member-pass",
                platform_role="member",
            )
            ensure_workspace_membership(
                state.workspace_store,
                membership_id="default:user:member",
                workspace_id="default",
                user_id="user:member",
                role="member",
            )
            state.job_service.submit(
                _future_spec(actor_id="user:member"),
                job_id="member-job",
                actor_id="user:member",
            )
            host = PlatformHost(state, start_path=repository_root)
            cookie = self._login(host, username="member", password="member-pass")

            status, payload, _headers = self._invoke(
                host,
                path="/api/jobs/member-job/cancel",
                method="POST",
                body={"reason": "force", "force": True},
                cookie=cookie,
            )
            job_state = state.job_service.get("member-job", workspace_id="default").state

        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "JobAuthorizationError")
        self.assertEqual(job_state, "queued")


def _future_spec(*, workspace_id: str = "default", actor_id: str = "agent-one"):
    expires_at = datetime(2099, 1, 1, tzinfo=UTC)
    spec = make_spec()
    return replace(
        spec,
        workspace_id=workspace_id,
        submitted_by_actor_id=actor_id,
        input_grants=(),
        output_grant=replace(spec.output_grant, expires_at=expires_at),  # type: ignore[arg-type]
        expires_at=expires_at,
    )


if __name__ == "__main__":
    unittest.main()
