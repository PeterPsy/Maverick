"""Tests for Phase 3 identity, workspace governance, and execution-policy models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from core.execution_policy.service import resolve_workspace_execution_profile, resolve_workspace_runtime_boundary
from core.identity.service import build_auth_session, build_password_credential, build_user_record, register_user
from core.identity.store import MongoIdentityStore, IdentityCollections
from core.workspaces.models import WorkspaceRecord
from core.workspaces.service import (
    build_workspace_record,
    create_workspace,
    default_workspace_governance,
    ensure_default_workspace_record,
    ensure_workspace_membership,
)
from core.workspaces.store import MongoWorkspaceStore, WorkspaceCollections


class FakeCollection:
    """Small in-memory collection for store tests."""

    def __init__(self) -> None:
        self.documents: list[dict] = []

    def find_one(self, query: dict) -> dict | None:
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return dict(document)
        return None

    def find(self, query: dict) -> list[dict]:
        return [dict(document) for document in self.documents if all(document.get(key) == value for key, value in query.items())]

    def update_one(self, query: dict, update: dict, *, upsert: bool = False) -> None:
        payload = dict(update.get("$set", {}))
        for index, document in enumerate(self.documents):
            if all(document.get(key) == value for key, value in query.items()):
                self.documents[index] = {**document, **payload}
                return
        if upsert:
            self.documents.append({**query, **payload})


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


class Phase3ModelTestCase(unittest.TestCase):
    """Verify the initial Phase 3 control-plane records and services."""

    def make_workspace_store(self) -> MongoWorkspaceStore:
        return MongoWorkspaceStore(
            WorkspaceCollections(
                workspaces=FakeCollection(),
                memberships=FakeCollection(),
                governance=FakeCollection(),
                quotas=FakeCollection(),
                active_workspace_selections=FakeCollection(),
            )
        )

    def make_identity_store(self) -> MongoIdentityStore:
        return MongoIdentityStore(
            IdentityCollections(
                users=FakeCollection(),
                credentials=FakeCollection(),
                auth_sessions=FakeCollection(),
            )
        )

    def test_identity_models_build_expected_records(self) -> None:
        now = datetime.now(tz=UTC)
        user = build_user_record(user_id="u1", username="piero", now=now, platform_role="admin")
        credential = build_password_credential(user_id="u1", password_hash="hash", algorithm="pbkdf2_sha256", now=now)
        session = build_auth_session(session_id="s1", user_id="u1", expires_at=now + timedelta(hours=1), now=now)

        self.assertEqual(user.platform_role, "admin")
        self.assertEqual(credential.algorithm, "pbkdf2_sha256")
        self.assertEqual(session.status, "active")

    def test_identity_service_accepts_non_mongo_store_contract(self) -> None:
        now = datetime.now(tz=UTC)
        user = build_user_record(user_id="u1", username="piero", now=now)
        credential = build_password_credential(user_id="u1", password_hash="hash", algorithm="pbkdf2_sha256", now=now)
        store = FakeIdentityStore()

        register_user(store, user, credential)

        self.assertEqual(store.get_user("u1").username, "piero")
        self.assertEqual(store.get_password_credential("u1").algorithm, "pbkdf2_sha256")

    def test_default_workspace_record_is_bootstrapped_immediately(self) -> None:
        store = self.make_workspace_store()
        workspace = ensure_default_workspace_record(store)

        self.assertEqual(workspace.workspace_id, "default")
        self.assertEqual(store.get_workspace("default").name, "Default")
        self.assertEqual(store.get_governance("default").workspace_id, "default")
        self.assertIsNone(store.get_quota("default").max_agent_instances)

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
        self.assertEqual(full_access_boundary.writable_roots, ["/"])


if __name__ == "__main__":
    unittest.main()
