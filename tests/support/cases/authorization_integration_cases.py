"""Regression tests for workspace authorization."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.app_sdk.cli import run_cli_json
from core.apps.contracts import (
    build_app_capabilities,
    build_app_contract,
    build_app_entrypoints,
    build_app_lifecycle,
    build_app_permissions,
    build_parsed_app_contract,
    build_provided_interface_declaration,
    build_required_interface_declaration,
    write_app_contract_file,
)
from core.apps.models import AppVisibilityDeclaration
from core.apps.service import install_store_app, register_app_source_from_contract
from core.cli.errors import CliInvocationNotAllowedError
from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.identity.service import create_user
from core.mcp.errors import McpInvocationNotAllowedError
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool, list_mcp_tools
from core.runtime.lifecycle import create_runtime_session
from core.runtime.runtime_session import RuntimeSessionGrantRecord
from core.runtime.workspace_api_token import issue_workspace_api_token, register_workspace_api_token
from core.runtime.service import queue_runtime_turn
from core.workspaces.service import ensure_workspace_membership
from tests.support.markers import slow_test_class


@slow_test_class("slow authorization integration suite; run with scripts/test_suite.py --level slow")
class AuthorizationIntegrationTestCase(unittest.TestCase):
    """Verify workspace roles, runtime ownership, and admin capabilities."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def invoke(
        self,
        app,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str | None = None,
        authorization: str | None = None,
        query_string: str = "",
    ) -> tuple[int, dict, dict[str, str]]:
        payload = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": query_string,
            "wsgi.input": BytesIO(payload),
        }
        if cookie:
            environ["HTTP_COOKIE"] = cookie
        if authorization:
            environ["HTTP_AUTHORIZATION"] = authorization

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        body_bytes = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), json.loads(body_bytes.decode("utf-8")), headers

    def login(self, app, *, username: str, password: str) -> str:
        status, _payload, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": username, "password": password},
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def login_admin(self, app) -> str:
        return self.login(
            app,
            username=os.environ.get("MAVERICK_ADMIN_USERNAME", "admin"),
            password=os.environ.get("MAVERICK_ADMIN_PASSWORD", "maverick"),
        )

    def create_workspace_users(self, state, workspace_id: str) -> tuple[object, object]:
        member = create_user(state.identity_store, username="member.a", password="member-pass", platform_role="member")
        workspace_admin = create_user(state.identity_store, username="workspace.admin", password="admin-pass", platform_role="member")
        ensure_workspace_membership(
            state.workspace_store,
            membership_id=f"{workspace_id}:{member.user_id}",
            workspace_id=workspace_id,
            user_id=member.user_id,
            role="member",
        )
        ensure_workspace_membership(
            state.workspace_store,
            membership_id=f"{workspace_id}:{workspace_admin.user_id}",
            workspace_id=workspace_id,
            user_id=workspace_admin.user_id,
            role="admin",
        )
        return member, workspace_admin

    def install_authorization_probe_app(
        self,
        state,
        repo_root: Path,
        *,
        workspace_id: str,
        visibility: AppVisibilityDeclaration,
    ) -> None:
        app_root = repo_root / "apps" / "authorization-probe"
        (app_root / "backend").mkdir(parents=True, exist_ok=True)
        (app_root / "backend" / "cli.py").write_text(
            "import json, sys\n"
            "payload = json.loads(sys.stdin.read() or '{}')\n"
            "print(json.dumps({'surface': payload.get('surface'), 'command_id': payload.get('command_id')}))\n",
            encoding="utf-8",
        )
        (app_root / "backend" / "mcp.py").write_text(
            "import json, sys\n"
            "payload = json.loads(sys.stdin.read() or '{}')\n"
            "print(json.dumps({'surface': payload.get('surface'), 'tool_name': payload.get('tool_name')}))\n",
            encoding="utf-8",
        )
        parsed = build_parsed_app_contract(
            app_id="authorization-probe",
            name="Authorization Probe",
            version="1.0.0",
            description="Authorization regression app.",
            publisher="maverick",
            contract=build_app_contract(
                visibility=visibility,
                capabilities=build_app_capabilities(
                    cli_commands=["probe"],
                    mcp_tools=["probe"],
                ),
                entrypoints=build_app_entrypoints(
                    cli="backend/cli.py",
                    mcp="backend/mcp.py",
                ),
            ),
        )
        write_app_contract_file(app_root, parsed)
        source = register_app_source_from_contract(
            state.app_store,
            source_kind="platform",
            source_path=str(app_root),
        )
        install_store_app(
            state.app_store,
            source_id=source.source_id,
            workspace_id=workspace_id,
            start_path=repo_root,
        )

    def install_dependency_probe_apps(self, state, repo_root: Path, *, workspace_id: str) -> None:
        provider_root = repo_root / "apps" / "dependency-provider"
        consumer_root = repo_root / "apps" / "dependency-consumer"
        provider_contract = build_parsed_app_contract(
            app_id="dependency-provider",
            name="Dependency Provider",
            version="1.0.0",
            description="Dependency provider regression app.",
            publisher="maverick",
            contract=build_app_contract(
                provides=[
                    build_provided_interface_declaration(
                        interface="authorization.probe",
                        description="Authorization probe provider.",
                    )
                ],
                lifecycle=build_app_lifecycle(install=False),
            ),
        )
        consumer_contract = build_parsed_app_contract(
            app_id="dependency-consumer",
            name="Dependency Consumer",
            version="1.0.0",
            description="Dependency consumer regression app.",
            publisher="maverick",
            contract=build_app_contract(
                requires=[
                    build_required_interface_declaration(
                        alias="agent-provider",
                        interface="authorization.probe",
                        description="Authorization probe dependency.",
                    )
                ],
                lifecycle=build_app_lifecycle(install=False),
            ),
        )
        write_app_contract_file(provider_root, provider_contract)
        write_app_contract_file(consumer_root, consumer_contract)
        for app_root in (provider_root, consumer_root):
            source = register_app_source_from_contract(
                state.app_store,
                source_kind="platform",
                source_path=str(app_root),
            )
            install_store_app(
                state.app_store,
                source_id=source.source_id,
                workspace_id=workspace_id,
                start_path=repo_root,
            )

    def install_runtime_owner_probe_app(self, state, repo_root: Path, *, workspace_id: str) -> None:
        app_root = repo_root / "apps" / "runtime-owner-probe"
        (app_root / "backend").mkdir(parents=True, exist_ok=True)
        (app_root / "backend" / "app.py").write_text(
            "import json\n"
            "print(json.dumps({\n"
            "  'ok': True,\n"
            "  'runtime_session_requests': [{\n"
            "    'request_id': 'runtime-owner-request',\n"
            "    'agent_id': 'chat',\n"
            "    'input_text': 'hello from app'\n"
            "  }]\n"
            "}))\n",
            encoding="utf-8",
        )
        parsed = build_parsed_app_contract(
            app_id="runtime-owner-probe",
            name="Runtime Owner Probe",
            version="1.0.0",
            description="Runtime owner regression app.",
            publisher="maverick",
            contract=build_app_contract(
                permissions=build_app_permissions(runtime_create_sessions=True),
                entrypoints=build_app_entrypoints(backend="backend/app.py"),
            ),
        )
        write_app_contract_file(app_root, parsed)
        source = register_app_source_from_contract(
            state.app_store,
            source_kind="platform",
            source_path=str(app_root),
        )
        install_store_app(
            state.app_store,
            source_id=source.source_id,
            workspace_id=workspace_id,
            start_path=repo_root,
        )

    def test_workspace_admin_controls_provider_selection_governance_and_membership(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login_admin(app)
        status_create, workspace, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Authorization Lab"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_create, 201)
        member, workspace_admin = self.create_workspace_users(state, workspace["workspace_id"])

        member_cookie = self.login(app, username="member.a", password="member-pass")
        workspace_admin_cookie = self.login(app, username="workspace.admin", password="admin-pass")

        status_member_provider, member_provider, _ = self.invoke(
            app,
            path="/api/providers/active",
            method="POST",
            body={"provider_id": "codex"},
            cookie=member_cookie,
        )
        status_admin_provider, admin_provider, _ = self.invoke(
            app,
            path="/api/providers/active",
            method="POST",
            body={"provider_id": "codex"},
            cookie=workspace_admin_cookie,
        )
        status_governance, governance, _ = self.invoke(
            app,
            path="/api/settings/workspace",
            method="PATCH",
            body={"allow_agent_creation": False},
            cookie=workspace_admin_cookie,
        )
        new_member = create_user(state.identity_store, username="member.b", password="member-b-pass", platform_role="member")
        status_membership, membership_payload, _ = self.invoke(
            app,
            path="/api/workspaces/memberships",
            method="PUT",
            body={"user_id": new_member.user_id, "role": "member"},
            cookie=workspace_admin_cookie,
        )

        self.assertEqual(status_member_provider, 403)
        self.assertEqual(member_provider["error"], "provider_selection_forbidden")
        self.assertEqual(status_admin_provider, 200)
        self.assertEqual(admin_provider["active_provider"]["provider_id"], "codex")
        self.assertEqual(status_governance, 200)
        self.assertFalse(governance["governance"]["allow_agent_creation"])
        self.assertEqual(status_membership, 200)
        self.assertEqual(membership_payload["membership"]["user_id"], new_member.user_id)
        self.assertEqual(membership_payload["membership"]["workspace_id"], workspace["workspace_id"])

    def test_runtime_owner_and_workspace_admin_boundaries_are_enforced(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login_admin(app)
        status_create, workspace, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Runtime Auth Lab"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_create, 201)
        member, _workspace_admin = self.create_workspace_users(state, workspace["workspace_id"])
        other_member = create_user(state.identity_store, username="member.other", password="other-pass", platform_role="member")
        ensure_workspace_membership(
            state.workspace_store,
            membership_id=f"{workspace['workspace_id']}:{other_member.user_id}",
            workspace_id=workspace["workspace_id"],
            user_id=other_member.user_id,
            role="member",
        )

        owner_cookie = self.login(app, username="member.a", password="member-pass")
        other_cookie = self.login(app, username="member.other", password="other-pass")
        workspace_admin_cookie = self.login(app, username="workspace.admin", password="admin-pass")
        status_session, session, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "worker"},
            cookie=owner_cookie,
        )
        status_other_cleanup, other_cleanup, _ = self.invoke(
            app,
            path=f"/api/runtime/sessions/{session['session_id']}/cleanup",
            method="POST",
            body={"reason": "not-owner"},
            cookie=other_cookie,
        )
        status_admin_cleanup, admin_cleanup, _ = self.invoke(
            app,
            path=f"/api/runtime/sessions/{session['session_id']}/cleanup",
            method="POST",
            body={"reason": "workspace-admin"},
            cookie=workspace_admin_cookie,
        )

        self.assertEqual(status_session, 201)
        self.assertEqual(session["owner_user_id"], member.user_id)
        self.assertEqual(status_other_cleanup, 403)
        self.assertEqual(other_cleanup["error"], "runtime_session_cleanup_forbidden")
        self.assertEqual(status_admin_cleanup, 200)
        self.assertEqual(admin_cleanup["session_id"], session["session_id"])

    def test_app_created_runtime_session_is_owned_by_calling_workspace_member(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login_admin(app)
        status_create, workspace, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "App Runtime Owner Lab"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_create, 201)
        member, _workspace_admin = self.create_workspace_users(state, workspace["workspace_id"])
        member_cookie = self.login(app, username="member.a", password="member-pass")
        self.install_runtime_owner_probe_app(state, repo_root, workspace_id=workspace["workspace_id"])

        def fake_submit_runtime_turn_async(state_arg, *, session, input_text, **_kwargs):
            turn = queue_runtime_turn(
                state_arg.runtime_store,
                turn_id="turn-app-owned-by-member",
                session_id=session.session_id,
                input_text=input_text,
            )
            return turn, []

        with patch("core.apps.runtime_requests.submit_runtime_turn_async", side_effect=fake_submit_runtime_turn_async):
            status_backend, backend_payload, _ = self.invoke(
                app,
                path="/api/apps/runtime-owner-probe/backend",
                method="POST",
                body={},
                cookie=member_cookie,
            )

        self.assertEqual(status_backend, 200)
        runtime_result = backend_payload["runtime_request_results"][0]
        session_id = runtime_result["runtime_session_id"]
        self.assertEqual(runtime_result["turn_id"], "turn-app-owned-by-member")
        session = state.runtime_store.get_session(session_id)
        self.assertEqual(session.owner_user_id, member.user_id)
        self.assertEqual(session.created_by_user_id, member.user_id)

        with (
            patch("core.api.runtime_api.interrupt_runtime_provider_turn", return_value=True),
            patch("core.api.runtime_api.dispatch_source_app_runtime_event", return_value=None),
        ):
            status_interrupt, interrupt_payload, _ = self.invoke(
                app,
                path="/api/runtime/turns/turn-app-owned-by-member/interrupt",
                method="POST",
                body={},
                cookie=member_cookie,
            )

        self.assertEqual(status_interrupt, 200)
        self.assertTrue(interrupt_payload["interrupted"])

    def test_member_cannot_mint_runtime_operation_grant_from_http_body(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login_admin(app)
        status_create, workspace, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Grant Escalation Lab"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_create, 201)
        self.create_workspace_users(state, workspace["workspace_id"])
        owner_cookie = self.login(app, username="member.a", password="member-pass")
        workspace_admin_cookie = self.login(app, username="workspace.admin", password="admin-pass")
        status_session, session, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "worker", "grants": ["cleanup"]},
            cookie=workspace_admin_cookie,
        )
        status_cleanup, cleanup, _ = self.invoke(
            app,
            path=f"/api/runtime/sessions/{session['session_id']}/cleanup",
            method="POST",
            body={"reason": "client-minted-grant"},
            cookie=owner_cookie,
        )

        self.assertEqual(status_session, 201)
        self.assertEqual(session["grants"], [])
        self.assertEqual(status_cleanup, 403)
        self.assertEqual(cleanup["error"], "runtime_session_cleanup_forbidden")

    def test_runtime_creation_obeys_workspace_governance_flags_and_quota(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login_admin(app)
        status_create, workspace, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Runtime Governance Lab"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_create, 201)
        self.create_workspace_users(state, workspace["workspace_id"])
        member_cookie = self.login(app, username="member.a", password="member-pass")
        workspace_admin_cookie = self.login(app, username="workspace.admin", password="admin-pass")

        governance = state.workspace_store.get_governance(workspace["workspace_id"])
        state.workspace_store.save_governance(replace(governance, allow_agent_creation=False))
        status_creation_disabled, creation_disabled, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "member-worker"},
            cookie=member_cookie,
        )

        governance = state.workspace_store.get_governance(workspace["workspace_id"])
        state.workspace_store.save_governance(
            replace(governance, allow_agent_creation=True, allow_agent_management=False)
        )
        status_management_member, management_member, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "member-worker"},
            cookie=member_cookie,
        )
        status_management_admin, management_admin, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "admin-worker"},
            cookie=workspace_admin_cookie,
        )

        governance = state.workspace_store.get_governance(workspace["workspace_id"])
        state.workspace_store.save_governance(replace(governance, allow_agent_management=True))
        quota = state.workspace_store.get_quota(workspace["workspace_id"])
        state.workspace_store.save_quota(replace(quota, max_agent_instances=1))
        status_quota, quota_payload, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "quota-worker"},
            cookie=workspace_admin_cookie,
        )

        self.assertEqual(status_creation_disabled, 403)
        self.assertEqual(creation_disabled["error"], "agent_creation_disabled")
        self.assertEqual(status_management_member, 403)
        self.assertEqual(management_member["error"], "agent_management_disabled")
        self.assertEqual(status_management_admin, 201)
        self.assertEqual(management_admin["agent_id"], "admin-worker")
        self.assertEqual(status_quota, 429)
        self.assertEqual(quota_payload["error"], "max_agent_instances_reached")

    def test_cross_workspace_runtime_operations_do_not_leak_authority(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login_admin(app)
        status_a, workspace_a, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Workspace A"},
            cookie=admin_cookie,
        )
        status_b, workspace_b, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Workspace B"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_a, 201)
        self.assertEqual(status_b, 201)
        member_a = create_user(state.identity_store, username="member.a", password="member-a-pass", platform_role="member")
        admin_a = create_user(state.identity_store, username="admin.a", password="admin-a-pass", platform_role="member")
        owner_b = create_user(state.identity_store, username="owner.b", password="owner-b-pass", platform_role="member")
        ensure_workspace_membership(
            state.workspace_store,
            membership_id=f"{workspace_a['workspace_id']}:{member_a.user_id}",
            workspace_id=workspace_a["workspace_id"],
            user_id=member_a.user_id,
            role="member",
        )
        ensure_workspace_membership(
            state.workspace_store,
            membership_id=f"{workspace_a['workspace_id']}:{admin_a.user_id}",
            workspace_id=workspace_a["workspace_id"],
            user_id=admin_a.user_id,
            role="admin",
        )
        ensure_workspace_membership(
            state.workspace_store,
            membership_id=f"{workspace_b['workspace_id']}:{owner_b.user_id}",
            workspace_id=workspace_b["workspace_id"],
            user_id=owner_b.user_id,
            role="member",
        )
        member_a_cookie = self.login(app, username="member.a", password="member-a-pass")
        admin_a_cookie = self.login(app, username="admin.a", password="admin-a-pass")
        owner_b_cookie = self.login(app, username="owner.b", password="owner-b-pass")
        status_session_b, session_b, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "worker-b"},
            cookie=owner_b_cookie,
        )
        self.assertEqual(status_session_b, 201)
        turn_b = queue_runtime_turn(
            state.runtime_store,
            turn_id="turn-workspace-b",
            session_id=session_b["session_id"],
            input_text="from b",
        )

        for cookie in (member_a_cookie, admin_a_cookie):
            status_cleanup, cleanup, _ = self.invoke(
                app,
                path=f"/api/runtime/sessions/{session_b['session_id']}/cleanup",
                method="POST",
                body={"reason": "cross-workspace"},
                cookie=cookie,
            )
            status_interrupt, interrupt, _ = self.invoke(
                app,
                path=f"/api/runtime/turns/{turn_b.turn_id}/interrupt",
                method="POST",
                body={},
                cookie=cookie,
            )
            status_restart, restart, _ = self.invoke(
                app,
                path="/api/recovery/restart-runtime",
                method="POST",
                body={"session_id": session_b["session_id"]},
                cookie=cookie,
            )

            self.assertEqual(status_cleanup, 404)
            self.assertEqual(cleanup["error"], "runtime_session_not_found")
            self.assertEqual(status_interrupt, 404)
            self.assertEqual(interrupt["error"], "runtime_turn_not_found")
            self.assertEqual(status_restart, 404)
            self.assertEqual(restart["error"], "runtime_session_not_found")

    def test_runtime_restart_cli_and_mcp_use_owner_admin_and_grants_not_agent_id_spoofing(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login_admin(app)
        status_a, workspace_a, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Restart CLI Auth A"},
            cookie=admin_cookie,
        )
        status_b, workspace_b, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Restart CLI Auth B"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_a, 201)
        self.assertEqual(status_b, 201)
        owner, workspace_admin = self.create_workspace_users(state, workspace_a["workspace_id"])
        other_member = create_user(state.identity_store, username="member.other", password="other-pass", platform_role="member")
        owner_b = create_user(state.identity_store, username="owner.b", password="owner-b-pass", platform_role="member")
        ensure_workspace_membership(
            state.workspace_store,
            membership_id=f"{workspace_a['workspace_id']}:{other_member.user_id}",
            workspace_id=workspace_a["workspace_id"],
            user_id=other_member.user_id,
            role="member",
        )
        ensure_workspace_membership(
            state.workspace_store,
            membership_id=f"{workspace_b['workspace_id']}:{owner_b.user_id}",
            workspace_id=workspace_b["workspace_id"],
            user_id=owner_b.user_id,
            role="member",
        )
        owner_cookie = self.login(app, username="member.a", password="member-pass")
        owner_b_cookie = self.login(app, username="owner.b", password="owner-b-pass")
        status_target, target_session, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "shared-agent"},
            cookie=owner_cookie,
        )
        status_cross, cross_session, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "workspace-b"},
            cookie=owner_b_cookie,
        )
        self.assertEqual(status_target, 201)
        self.assertEqual(status_cross, 201)

        def cli_context(*, user_id: str, agent_id: str | None, workspace_role: str) -> CliInvocationContext:
            return CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id=workspace_a["workspace_id"],
                agent_id=agent_id,
                effective_mode="sandbox",
                platform_role="member",
                user_id=user_id,
                workspace_role=workspace_role,
            )

        def mcp_context(context: CliInvocationContext) -> McpInvocationContext:
            return McpInvocationContext(**context.__dict__)

        def run_restart_cli(context: CliInvocationContext, session_id: str) -> dict:
            return run_core_cli_command(
                command_id="core.recovery.restart",
                context=context,
                arguments={"session_id": session_id, "reason": "authorization-regression"},
                runtime_store=state.runtime_store,
                recovery_store=state.recovery_store,
                workspace_store=state.workspace_store,
                workspace_id=context.workspace_id,
                start_path=repo_root,
            )

        def run_restart_mcp(context: McpInvocationContext, session_id: str) -> dict:
            return call_mcp_tool(
                tool_name="core.recovery.restart",
                context=context,
                arguments={"session_id": session_id, "reason": "authorization-regression"},
                runtime_store=state.runtime_store,
                recovery_store=state.recovery_store,
                workspace_store=state.workspace_store,
                workspace_id=context.workspace_id,
                start_path=repo_root,
            )

        spoofed_cli = cli_context(user_id=other_member.user_id, agent_id="shared-agent", workspace_role="admin")
        with self.assertRaises(CliInvocationNotAllowedError):
            run_restart_cli(spoofed_cli, target_session["session_id"])
        with self.assertRaises(McpInvocationNotAllowedError):
            run_restart_mcp(mcp_context(spoofed_cli), target_session["session_id"])

        owner_cli = cli_context(
            user_id=owner.user_id,
            agent_id=target_session["session_id"],
            workspace_role="member",
        )
        owner_result = run_restart_cli(owner_cli, target_session["session_id"])
        self.assertTrue(owner_result["executed"])

        admin_cli = cli_context(
            user_id=workspace_admin.user_id,
            agent_id="admin-runtime",
            workspace_role="admin",
        )
        admin_result = run_restart_mcp(mcp_context(admin_cli), target_session["session_id"])
        self.assertTrue(admin_result["executed"])

        session_record = state.runtime_store.get_session(target_session["session_id"])
        state.runtime_store.save_session(
            replace(
                session_record,
                grants=[
                    {
                        "source": "platform",
                        "operation": "restart",
                        "grantee_kind": "user",
                        "grantee_id": other_member.user_id,
                    }
                ],
            )
        )
        granted_cli = cli_context(user_id=other_member.user_id, agent_id="other-runtime", workspace_role="member")
        granted_result = run_restart_cli(granted_cli, target_session["session_id"])
        self.assertTrue(granted_result["executed"])

        with self.assertRaises(CliInvocationNotAllowedError):
            run_restart_cli(admin_cli, cross_session["session_id"])
        with self.assertRaises(McpInvocationNotAllowedError):
            run_restart_mcp(mcp_context(admin_cli), cross_session["session_id"])

    def test_app_cli_and_mcp_visibility_follow_workspace_roles(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login_admin(app)
        status_create, workspace, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "App Surface Auth Lab"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_create, 201)
        member, workspace_admin = self.create_workspace_users(state, workspace["workspace_id"])
        self.install_authorization_probe_app(
            state,
            repo_root,
            workspace_id=workspace["workspace_id"],
            visibility=AppVisibilityDeclaration(platform_roles=None, workspace_roles=["admin"], capabilities=None),
        )
        member_cli = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id=workspace["workspace_id"],
            agent_id="member-runtime",
            effective_mode="sandbox",
            platform_role="member",
            user_id=member.user_id,
            workspace_role="member",
        )
        admin_cli = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id=workspace["workspace_id"],
            agent_id="admin-runtime",
            effective_mode="sandbox",
            platform_role="member",
            user_id=workspace_admin.user_id,
            workspace_role="admin",
        )
        member_mcp = McpInvocationContext(**member_cli.__dict__)
        admin_mcp = McpInvocationContext(**admin_cli.__dict__)

        member_commands = list_core_cli_commands(
            app_store=state.app_store,
            workspace_store=state.workspace_store,
            workspace_id=workspace["workspace_id"],
            start_path=repo_root,
            context=member_cli,
        )
        admin_commands = list_core_cli_commands(
            app_store=state.app_store,
            workspace_store=state.workspace_store,
            workspace_id=workspace["workspace_id"],
            start_path=repo_root,
            context=admin_cli,
        )
        member_tools = list_mcp_tools(
            app_store=state.app_store,
            workspace_store=state.workspace_store,
            workspace_id=workspace["workspace_id"],
            start_path=repo_root,
            context=member_mcp,
        )
        admin_tools = list_mcp_tools(
            app_store=state.app_store,
            workspace_store=state.workspace_store,
            workspace_id=workspace["workspace_id"],
            start_path=repo_root,
            context=admin_mcp,
        )

        self.assertNotIn("app.authorization-probe.probe", [command.command_id for command in member_commands])
        self.assertIn("app.authorization-probe.probe", [command.command_id for command in admin_commands])
        self.assertNotIn("app.authorization-probe.probe", [tool.tool_name for tool in member_tools])
        self.assertIn("app.authorization-probe.probe", [tool.tool_name for tool in admin_tools])
        direct_apps = run_cli_json(
            [
                "apps",
                "list",
                "--json",
                "--workspace",
                workspace["workspace_id"],
            ],
            state=state,
            repository_root=repo_root,
        )
        self.assertNotIn("authorization-probe", [item["app_id"] for item in direct_apps["apps"]])
        for spoofed_args in (
            [
                "apps",
                "list",
                "--json",
                "--workspace",
                workspace["workspace_id"],
                "--platform-role",
                "admin",
            ],
            [
                "apps",
                "list",
                "--json",
                "--workspace",
                workspace["workspace_id"],
                "--workspace-role",
                "admin",
            ],
            [
                "app",
                "authorization-probe",
                "cli",
                "list",
                "--json",
                "--workspace",
                workspace["workspace_id"],
                "--platform-role",
                "admin",
            ],
            [
                "app",
                "authorization-probe",
                "mcp",
                "list",
                "--json",
                "--workspace",
                workspace["workspace_id"],
                "--workspace-role",
                "admin",
            ],
        ):
            with self.assertRaises(SystemExit):
                run_cli_json(spoofed_args, state=state, repository_root=repo_root)
        with self.assertRaises(CliInvocationNotAllowedError):
            run_core_cli_command(
                command_id="app.authorization-probe.probe",
                context=member_cli,
                app_store=state.app_store,
                workspace_store=state.workspace_store,
                workspace_id=workspace["workspace_id"],
                start_path=repo_root,
            )
        with self.assertRaises(McpInvocationNotAllowedError):
            call_mcp_tool(
                tool_name="app.authorization-probe.probe",
                context=member_mcp,
                app_store=state.app_store,
                workspace_store=state.workspace_store,
                workspace_id=workspace["workspace_id"],
                start_path=repo_root,
            )

    def test_visibility_capabilities_are_enforced_for_app_surfaces(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login_admin(app)
        status_create, workspace, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Capability Visibility Lab"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_create, 201)
        member, workspace_admin = self.create_workspace_users(state, workspace["workspace_id"])
        self.install_authorization_probe_app(
            state,
            repo_root,
            workspace_id=workspace["workspace_id"],
            visibility=AppVisibilityDeclaration(
                platform_roles=None,
                workspace_roles=None,
                capabilities=["manage_runtime_sessions"],
            ),
        )
        member_cli = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id=workspace["workspace_id"],
            agent_id="member-runtime",
            effective_mode="sandbox",
            platform_role="member",
            user_id=member.user_id,
            workspace_role="member",
        )
        admin_cli = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id=workspace["workspace_id"],
            agent_id="admin-runtime",
            effective_mode="sandbox",
            platform_role="member",
            user_id=workspace_admin.user_id,
            workspace_role="admin",
        )

        member_commands = list_core_cli_commands(
            app_store=state.app_store,
            workspace_store=state.workspace_store,
            workspace_id=workspace["workspace_id"],
            start_path=repo_root,
            context=member_cli,
        )
        admin_commands = list_core_cli_commands(
            app_store=state.app_store,
            workspace_store=state.workspace_store,
            workspace_id=workspace["workspace_id"],
            start_path=repo_root,
            context=admin_cli,
        )

        self.assertNotIn("app.authorization-probe.probe", [command.command_id for command in member_commands])
        self.assertIn("app.authorization-probe.probe", [command.command_id for command in admin_commands])

    def test_app_dependency_selection_requires_workspace_admin_but_lookup_is_readable(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login_admin(app)
        status_create, workspace, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Dependency Auth Lab"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_create, 201)
        self.create_workspace_users(state, workspace["workspace_id"])
        self.install_dependency_probe_apps(state, repo_root, workspace_id=workspace["workspace_id"])
        member_cookie = self.login(app, username="member.a", password="member-pass")
        workspace_admin_cookie = self.login(app, username="workspace.admin", password="admin-pass")

        status_lookup, lookup, _ = self.invoke(
            app,
            path="/api/apps/dependencies",
            query_string="consumer_app_id=dependency-consumer",
            cookie=member_cookie,
        )
        status_member_post, member_post, _ = self.invoke(
            app,
            path="/api/apps/dependencies",
            method="POST",
            body={
                "consumer_app_id": "dependency-consumer",
                "alias": "agent-provider",
                "provider_app_ids": ["dependency-provider"],
            },
            cookie=member_cookie,
        )
        status_admin_post, admin_post, _ = self.invoke(
            app,
            path="/api/apps/dependencies",
            method="POST",
            body={
                "consumer_app_id": "dependency-consumer",
                "alias": "agent-provider",
                "provider_app_ids": ["dependency-provider"],
            },
            cookie=workspace_admin_cookie,
        )
        status_lookup_after, lookup_after, _ = self.invoke(
            app,
            path="/api/apps/dependencies",
            query_string="consumer_app_id=dependency-consumer",
            cookie=member_cookie,
        )

        self.assertEqual(status_lookup, 200)
        self.assertEqual(lookup["status"], "blocked")
        self.assertEqual(lookup["dependencies"][0]["candidates"][0]["app_id"], "dependency-provider")
        self.assertEqual(status_member_post, 403)
        self.assertEqual(member_post["error"], "app_dependency_management_forbidden")
        self.assertEqual(status_admin_post, 200)
        self.assertEqual(admin_post["status"], "resolved")
        self.assertEqual(admin_post["dependencies"][0]["selected_provider_app_ids"], ["dependency-provider"])
        self.assertEqual(status_lookup_after, 200)
        self.assertEqual(lookup_after["status"], "resolved")

    def test_runtime_cli_derives_mode_from_session_not_client_payload(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login_admin(app)
        status_session, session, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "sandboxed", "requested_mode": "sandbox"},
            cookie=cookie,
        )
        token = issue_workspace_api_token(workspace_id=session["workspace_id"], runtime_session_id=session["session_id"])
        register_workspace_api_token(state.runtime_store, token)
        status_cli, payload, _ = self.invoke(
            app,
            path="/api/runtime/cli",
            method="POST",
            body={
                "argv": ["core", "cli", "run", "core.recovery.restart_backend", "--json"],
                "effective_mode": "full-access",
            },
            authorization=f"Bearer {token}",
        )

        self.assertEqual(status_session, 201)
        self.assertEqual(session["effective_mode"], "sandbox")
        self.assertEqual(status_cli, 400)
        self.assertIn("Sandboxed agents", payload["detail"])

    def test_runtime_cli_requires_active_owner_workspace_membership(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login_admin(app)
        status_create, workspace, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Runtime Token Membership Lab"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_create, 201)
        member, _workspace_admin = self.create_workspace_users(state, workspace["workspace_id"])
        self.install_authorization_probe_app(
            state,
            repo_root,
            workspace_id=workspace["workspace_id"],
            visibility=AppVisibilityDeclaration(platform_roles=None, workspace_roles=None, capabilities=None),
        )
        member_cookie = self.login(app, username="member.a", password="member-pass")
        status_session, session, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "member-runtime"},
            cookie=member_cookie,
        )
        self.assertEqual(status_session, 201)
        membership = state.workspace_store.get_membership(user_id=member.user_id, workspace_id=workspace["workspace_id"])
        state.workspace_store.save_membership(replace(membership, status="inactive"))
        token = issue_workspace_api_token(workspace_id=session["workspace_id"], runtime_session_id=session["session_id"])
        register_workspace_api_token(state.runtime_store, token)

        def assert_runtime_cli_denied() -> None:
            runtime_cli_requests = [
                ["apps", "list", "--json"],
                ["app", "authorization-probe", "cli", "list", "--json"],
                ["app", "authorization-probe", "mcp", "list", "--json"],
            ]
            for argv in runtime_cli_requests:
                status_cli, payload, _ = self.invoke(
                    app,
                    path="/api/runtime/cli",
                    method="POST",
                    body={"argv": argv},
                    authorization=f"Bearer {token}",
                )
                self.assertEqual(status_cli, 401)
                self.assertEqual(payload["error"], "runtime_session_owner_not_authorized")

        assert_runtime_cli_denied()
        state.workspace_store.save_membership(replace(membership, status="active"))
        state.workspace_store.delete_memberships_for_user(member.user_id)
        assert_runtime_cli_denied()

    def test_runtime_restart_cli_and_mcp_use_owner_admin_and_grant_authority(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login_admin(app)
        status_a, workspace_a, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Restart Workspace A"},
            cookie=admin_cookie,
        )
        status_b, workspace_b, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Restart Workspace B"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_a, 201)
        self.assertEqual(status_b, 201)
        owner = create_user(state.identity_store, username="restart.owner", password="owner-pass", platform_role="member")
        non_owner = create_user(state.identity_store, username="restart.other", password="other-pass", platform_role="member")
        workspace_admin = create_user(state.identity_store, username="restart.admin", password="admin-pass", platform_role="member")
        grantee = create_user(state.identity_store, username="restart.grantee", password="grant-pass", platform_role="member")
        owner_b = create_user(state.identity_store, username="restart.owner.b", password="owner-b-pass", platform_role="member")
        for user, role in (
            (owner, "member"),
            (non_owner, "member"),
            (workspace_admin, "admin"),
            (grantee, "member"),
        ):
            ensure_workspace_membership(
                state.workspace_store,
                membership_id=f"{workspace_a['workspace_id']}:{user.user_id}",
                workspace_id=workspace_a["workspace_id"],
                user_id=user.user_id,
                role=role,
            )
        ensure_workspace_membership(
            state.workspace_store,
            membership_id=f"{workspace_b['workspace_id']}:{owner_b.user_id}",
            workspace_id=workspace_b["workspace_id"],
            user_id=owner_b.user_id,
            role="member",
        )
        session = create_runtime_session(
            state.runtime_store,
            session_id="restart-session-a",
            workspace_id=workspace_a["workspace_id"],
            agent_id="shared-agent",
            owner_user_id=owner.user_id,
            created_by_user_id=owner.user_id,
            start_path=repo_root,
        )
        state.runtime_store.save_session(
            replace(
                session,
                grants=[
                    RuntimeSessionGrantRecord(
                        operation="restart",
                        grantee_kind="user",
                        grantee_id=grantee.user_id,
                        issued_by_user_id=workspace_admin.user_id,
                    )
                ],
            )
        )
        non_owner_cli = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id=workspace_a["workspace_id"],
            agent_id="shared-agent",
            effective_mode="sandbox",
            platform_role="member",
            user_id=non_owner.user_id,
            workspace_role="member",
        )
        owner_cli = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id=workspace_a["workspace_id"],
            agent_id="owner-runtime",
            effective_mode="sandbox",
            platform_role="member",
            user_id=owner.user_id,
            workspace_role="member",
        )
        grantee_cli = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id=workspace_a["workspace_id"],
            agent_id="grantee-runtime",
            effective_mode="sandbox",
            platform_role="member",
            user_id=grantee.user_id,
            workspace_role="member",
        )
        admin_mcp = McpInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id=workspace_a["workspace_id"],
            agent_id="admin-runtime",
            effective_mode="sandbox",
            platform_role="member",
            user_id=workspace_admin.user_id,
            workspace_role="admin",
        )
        cross_workspace_mcp = McpInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id=workspace_b["workspace_id"],
            agent_id="owner-b-runtime",
            effective_mode="sandbox",
            platform_role="member",
            user_id=owner_b.user_id,
            workspace_role="member",
        )

        with self.assertRaises(CliInvocationNotAllowedError):
            run_core_cli_command(
                command_id="core.recovery.restart",
                context=non_owner_cli,
                arguments={"session_id": session.session_id, "reason": "same agent id should not authorize"},
                runtime_store=state.runtime_store,
                recovery_store=state.recovery_store,
                workspace_store=state.workspace_store,
                workspace_id=workspace_a["workspace_id"],
                start_path=repo_root,
            )
        owner_result = run_core_cli_command(
            command_id="core.recovery.restart",
            context=owner_cli,
            arguments={"session_id": session.session_id, "reason": "owner restart"},
            runtime_store=state.runtime_store,
            recovery_store=state.recovery_store,
            workspace_store=state.workspace_store,
            workspace_id=workspace_a["workspace_id"],
            start_path=repo_root,
        )
        admin_result = call_mcp_tool(
            tool_name="core.recovery.restart",
            context=admin_mcp,
            arguments={"session_id": session.session_id, "reason": "admin restart"},
            runtime_store=state.runtime_store,
            recovery_store=state.recovery_store,
            workspace_store=state.workspace_store,
            workspace_id=workspace_a["workspace_id"],
            start_path=repo_root,
        )
        grantee_result = run_core_cli_command(
            command_id="core.recovery.restart",
            context=grantee_cli,
            arguments={"session_id": session.session_id, "reason": "grant restart"},
            runtime_store=state.runtime_store,
            recovery_store=state.recovery_store,
            workspace_store=state.workspace_store,
            workspace_id=workspace_a["workspace_id"],
            start_path=repo_root,
        )
        with self.assertRaises(McpInvocationNotAllowedError):
            call_mcp_tool(
                tool_name="core.recovery.restart",
                context=cross_workspace_mcp,
                arguments={"session_id": session.session_id, "reason": "cross workspace"},
                runtime_store=state.runtime_store,
                recovery_store=state.recovery_store,
                workspace_store=state.workspace_store,
                workspace_id=workspace_b["workspace_id"],
                start_path=repo_root,
            )

        self.assertTrue(owner_result["executed"])
        self.assertTrue(admin_result["executed"])
        self.assertTrue(grantee_result["executed"])
        with self.assertRaises(CliInvocationNotAllowedError):
            run_cli_json(
                [
                    "core",
                    "cli",
                    "run",
                    "core.recovery.restart",
                    "--json",
                    "--workspace",
                    workspace_a["workspace_id"],
                    "--arguments-json",
                    json.dumps({"session_id": session.session_id}),
                    "--user-id",
                    owner.user_id,
                    "--workspace-role",
                    "admin",
                ],
                state=state,
                repository_root=repo_root,
            )

    def test_backend_restart_requires_admin_capability_on_cli_and_mcp(self) -> None:
        repo_root = self.make_repo_root()
        admin_cli = CliInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="sess-admin",
            effective_mode="full-access",
            workspace_role="admin",
        )
        member_cli = CliInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="sess-member",
            effective_mode="full-access",
            workspace_role="member",
        )
        with patch("core.cli.recovery_commands.restart_backend_service") as restart_backend:
            restart_backend.return_value.to_payload.return_value = {"restarted": True}
            result = run_core_cli_command(
                command_id="core.recovery.restart_backend",
                context=admin_cli,
                workspace_id="default",
                start_path=repo_root,
            )
        self.assertTrue(result["restarted"])
        with self.assertRaises(CliInvocationNotAllowedError):
            run_core_cli_command(
                command_id="core.recovery.restart_backend",
                context=member_cli,
                workspace_id="default",
                start_path=repo_root,
            )

        admin_mcp = McpInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="sess-admin",
            effective_mode="full-access",
            workspace_role="admin",
        )
        member_mcp = McpInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="sess-member",
            effective_mode="full-access",
            workspace_role="member",
        )
        with patch("core.mcp.recovery_tools.restart_backend_service") as restart_backend:
            restart_backend.return_value.to_payload.return_value = {"restarted": True}
            result = call_mcp_tool(
                tool_name="core.recovery.restart_backend",
                context=admin_mcp,
                workspace_id="default",
                start_path=repo_root,
            )
        self.assertTrue(result["restarted"])
        with self.assertRaises(McpInvocationNotAllowedError):
            call_mcp_tool(
                tool_name="core.recovery.restart_backend",
                context=member_mcp,
                workspace_id="default",
                start_path=repo_root,
            )
        with self.assertRaises(CliInvocationNotAllowedError):
            run_cli_json(
                [
                    "core",
                    "cli",
                    "run",
                    "core.recovery.restart_backend",
                    "--json",
                    "--workspace",
                    "default",
                    "--caller-kind",
                    "full_access_agent",
                    "--effective-mode",
                    "full-access",
                    "--workspace-role",
                    "admin",
                ],
                state=bootstrap_platform_state(start_path=repo_root),
                repository_root=repo_root,
            )
