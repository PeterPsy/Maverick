"""Tests for identity, workspace governance, and execution-policy models."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest

from core.api.session_api import SESSION_COOKIE, resolve_request_session
from core.execution_policy.service import resolve_workspace_execution_profile, resolve_workspace_runtime_boundary
from core.identity.errors import UserNotFoundError
from core.identity.service import (
    authenticate_password,
    bootstrap_default_admin,
    build_auth_session,
    build_password_credential,
    build_user_record,
    register_user,
    set_user_password,
    update_user,
)
from core.identity.store import IdentityDocumentStore, IdentityCollections
from core.workspaces.models import WorkspaceRecord
from core.workspaces.service import (
    create_workspace,
    default_workspace_governance,
    ensure_default_workspace_record,
    ensure_workspace_membership,
    resolve_active_workspace_for_user,
    set_active_workspace_for_user,
)
from core.workspaces.store import WorkspaceDocumentStore, WorkspaceCollections
from tests.support.collections import FakeCollection


class FakeIdentityStore:
    """Small in-memory identity store used to prove service-layer agnosticism."""

    def __init__(self) -> None:
        self.users: dict[str, object] = {}
        self.credentials: dict[str, object] = {}

    def save_user(self, record):
        self.users[record.user_id] = record
        return record

    def get_user(self, user_id: str):
        return self.users[user_id]

    def get_user_by_username(self, username: str):
        for record in self.users.values():
            if record.username == username:
                return record
        raise KeyError(username)

    def save_password_credential(self, record):
        self.credentials[record.user_id] = record
        return record

    def get_password_credential(self, user_id: str):
        return self.credentials[user_id]

    def save_auth_session(self, record):
        return record

    def get_auth_session(self, session_id: str):
        raise KeyError(session_id)


class IdentityWorkspaceModelTestCase(unittest.TestCase):
    """Verify the initial control-plane records and services."""

    def make_workspace_store(self) -> WorkspaceDocumentStore:
        return WorkspaceDocumentStore(
            WorkspaceCollections(
                workspaces=FakeCollection(),
                memberships=FakeCollection(),
                governance=FakeCollection(),
                quotas=FakeCollection(),
                active_workspace_selections=FakeCollection(),
            )
        )

    def make_identity_store(self) -> IdentityDocumentStore:
        return IdentityDocumentStore(
            IdentityCollections(
                users=FakeCollection(),
                credentials=FakeCollection(),
                auth_sessions=FakeCollection(),
            )
        )

    def test_identity_models_build_expected_records(self) -> None:
        now = datetime.now(tz=UTC)
        user = build_user_record(user_id="u1", username="alice", now=now, platform_role="admin")
        credential = build_password_credential(user_id="u1", password_hash="hash", algorithm="pbkdf2_sha256", now=now)
        session = build_auth_session(session_id="s1", user_id="u1", expires_at=now + timedelta(hours=1), now=now)

        self.assertEqual(user.platform_role, "admin")
        self.assertEqual(credential.algorithm, "pbkdf2_sha256")
        self.assertEqual(session.status, "active")

    def test_identity_service_accepts_non_mongo_store_contract(self) -> None:
        now = datetime.now(tz=UTC)
        user = build_user_record(user_id="u1", username="alice", now=now)
        credential = build_password_credential(user_id="u1", password_hash="hash", algorithm="pbkdf2_sha256", now=now)
        store = FakeIdentityStore()

        register_user(store, user, credential)

        self.assertEqual(store.get_user("u1").username, "alice")
        self.assertEqual(store.get_password_credential("u1").algorithm, "pbkdf2_sha256")

    def test_bootstrap_admin_password_tracks_supplied_install_secret(self) -> None:
        identity_store = self.make_identity_store()
        workspace_store = self.make_workspace_store()
        bootstrap_default_admin(identity_store, workspace_store, username="admin", password="old-password")

        bootstrap_default_admin(identity_store, workspace_store, username="admin", password="new-password")

        self.assertEqual(authenticate_password(identity_store, username="admin", password="new-password").username, "admin")
        with self.assertRaises(UserNotFoundError):
            authenticate_password(identity_store, username="admin", password="old-password")

    def test_bootstrap_admin_without_password_preserves_existing_password(self) -> None:
        identity_store = self.make_identity_store()
        workspace_store = self.make_workspace_store()
        bootstrap_default_admin(identity_store, workspace_store, username="admin", password="old-password")

        bootstrap_default_admin(identity_store, workspace_store, username="admin", password=None)

        self.assertEqual(authenticate_password(identity_store, username="admin", password="old-password").username, "admin")

    def test_bootstrap_admin_without_password_can_create_locked_admin(self) -> None:
        identity_store = self.make_identity_store()
        workspace_store = self.make_workspace_store()

        user = bootstrap_default_admin(identity_store, workspace_store, username="admin", password=None)

        self.assertEqual(user.username, "admin")
        with self.assertRaises(UserNotFoundError):
            identity_store.get_password_credential(user.user_id)

    def test_bootstrap_admin_recreates_missing_password_credential(self) -> None:
        identity_store = self.make_identity_store()
        workspace_store = self.make_workspace_store()
        identity_store.save_user(build_user_record(user_id="user:admin", username="admin", platform_role="admin"))

        bootstrap_default_admin(identity_store, workspace_store, username="admin", password="install-password")

        self.assertEqual(authenticate_password(identity_store, username="admin", password="install-password").username, "admin")

    def test_password_reset_revokes_existing_auth_sessions(self) -> None:
        identity_store = self.make_identity_store()
        now = datetime(2026, 4, 29, tzinfo=UTC)
        identity_store.save_user(build_user_record(user_id="user:alice", username="alice", now=now))
        identity_store.save_auth_session(
            build_auth_session(
                session_id="session-1",
                user_id="user:alice",
                expires_at=now + timedelta(hours=1),
                now=now,
            )
        )

        set_user_password(identity_store, user_id="user:alice", password="new-password", now=now + timedelta(minutes=1))

        session = identity_store.get_auth_session("session-1")
        self.assertEqual(session.status, "revoked")
        self.assertEqual(session.updated_at, now + timedelta(minutes=1))

    def test_user_deactivation_revokes_existing_auth_sessions(self) -> None:
        identity_store = self.make_identity_store()
        now = datetime(2026, 4, 29, tzinfo=UTC)
        identity_store.save_user(build_user_record(user_id="user:alice", username="alice", now=now))
        identity_store.save_auth_session(
            build_auth_session(
                session_id="session-1",
                user_id="user:alice",
                expires_at=now + timedelta(hours=1),
                now=now,
            )
        )

        update_user(identity_store, user_id="user:alice", is_active=False, now=now + timedelta(minutes=1))

        session = identity_store.get_auth_session("session-1")
        self.assertEqual(session.status, "revoked")
        self.assertEqual(session.updated_at, now + timedelta(minutes=1))

    def test_request_session_refuses_inactive_user(self) -> None:
        identity_store = self.make_identity_store()
        workspace_store = self.make_workspace_store()
        now = datetime(2026, 4, 29, tzinfo=UTC)
        identity_store.save_user(
            build_user_record(user_id="user:alice", username="alice", is_active=False, now=now)
        )
        identity_store.save_auth_session(
            build_auth_session(
                session_id="session-1",
                user_id="user:alice",
                expires_at=now + timedelta(hours=1),
                now=now,
            )
        )
        ensure_workspace_membership(
            workspace_store,
            membership_id="default:user:alice",
            workspace_id="default",
            user_id="user:alice",
            role="admin",
            now=now,
        )
        set_active_workspace_for_user(workspace_store, user_id="user:alice", workspace_id="default", now=now)

        context = resolve_request_session(
            SimpleNamespace(identity_store=identity_store, workspace_store=workspace_store),
            {"HTTP_COOKIE": f"{SESSION_COOKIE}=session-1"},
        )

        self.assertIsNone(context)
        self.assertIsNone(identity_store.get_auth_session("session-1").last_seen_at)

    def test_default_workspace_record_is_bootstrapped_immediately(self) -> None:
        store = self.make_workspace_store()
        workspace = ensure_default_workspace_record(store)

        self.assertEqual(workspace.workspace_id, "default")
        self.assertEqual(store.get_workspace("default").name, "Default")
        self.assertEqual(store.get_governance("default").workspace_id, "default")
        self.assertIsNone(store.get_quota("default").max_agent_instances)

    def test_default_workspace_bootstrap_preserves_existing_governance_and_quota(self) -> None:
        store = self.make_workspace_store()
        ensure_default_workspace_record(store)
        governance = replace(store.get_governance("default"), allow_custom_apps=False, allow_full_access_runtime=False)
        quota = replace(store.get_quota("default"), max_agent_instances=1)
        store.save_governance(governance)
        store.save_quota(quota)

        ensure_default_workspace_record(store)

        self.assertFalse(store.get_governance("default").allow_custom_apps)
        self.assertFalse(store.get_governance("default").allow_full_access_runtime)
        self.assertEqual(store.get_quota("default").max_agent_instances, 1)

    def test_active_workspace_resolution_skips_archived_workspaces(self) -> None:
        store = self.make_workspace_store()
        now = datetime(2026, 4, 29, tzinfo=UTC)
        default_workspace = ensure_default_workspace_record(store, now=now)
        store.save_workspace(replace(default_workspace, status="archived", updated_at=now + timedelta(minutes=1)))
        active_workspace = create_workspace(store, name="Active Workspace", created_by_user_id="u1", now=now)
        ensure_workspace_membership(
            store,
            membership_id="default:u1",
            workspace_id="default",
            user_id="u1",
            role="admin",
            now=now,
        )
        set_active_workspace_for_user(store, user_id="u1", workspace_id="default", now=now)

        resolved = resolve_active_workspace_for_user(store, user_id="u1", now=now + timedelta(minutes=2))

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.workspace_id, active_workspace.workspace_id)

    def test_create_workspace_adds_registry_governance_and_quota(self) -> None:
        store = self.make_workspace_store()
        workspace = create_workspace(store, name="Acme Workspace", created_by_user_id="u1")

        self.assertIsInstance(workspace, WorkspaceRecord)
        self.assertEqual(workspace.workspace_id, "acme-workspace")
        self.assertEqual(store.get_governance(workspace.workspace_id).workspace_id, workspace.workspace_id)
        self.assertEqual(store.get_quota(workspace.workspace_id).max_agent_instances, 3)
        self.assertEqual(store.get_membership(user_id="u1", workspace_id=workspace.workspace_id).role, "admin")
        self.assertEqual(store.get_active_workspace("u1").workspace_id, workspace.workspace_id)

    def test_create_workspace_makes_slug_unique(self) -> None:
        store = self.make_workspace_store()
        first = create_workspace(store, name="Acme Workspace", created_by_user_id="u1")
        second = create_workspace(store, name="Acme Workspace", created_by_user_id="u1")

        self.assertEqual(first.workspace_id, "acme-workspace")
        self.assertEqual(second.workspace_id, "acme-workspace-2")

    def test_membership_can_be_persisted(self) -> None:
        store = self.make_workspace_store()
        membership = ensure_workspace_membership(
            store,
            membership_id="m1",
            workspace_id="default",
            user_id="u1",
            role="admin",
        )

        self.assertEqual(membership.role, "admin")
        self.assertEqual(store.get_membership(user_id="u1", workspace_id="default").membership_id, "m1")

    def test_execution_policy_enforces_default_vs_non_default(self) -> None:
        default_governance = default_workspace_governance("default")
        default_profile = resolve_workspace_execution_profile(
            "default",
            requested_mode="full-access",
            governance=default_governance,
            platform_allows_full_access=True,
        )
        isolated_profile = resolve_workspace_execution_profile("acme", requested_mode="full-access")
        denied_default_profile = resolve_workspace_execution_profile(
            "default",
            requested_mode="full-access",
            governance=default_governance,
            platform_allows_full_access=False,
        )
        full_access_boundary = resolve_workspace_runtime_boundary(
            "default",
            requested_mode="full-access",
            governance=default_governance,
            platform_allows_full_access=True,
        )

        self.assertEqual(default_profile.effective_mode, "full-access")
        self.assertEqual(isolated_profile.effective_mode, "sandbox")
        self.assertEqual(denied_default_profile.effective_mode, "sandbox")
        self.assertEqual(full_access_boundary.readable_roots, ["/"])
        self.assertEqual(full_access_boundary.writable_roots, ["/"])


if __name__ == "__main__":
    unittest.main()
