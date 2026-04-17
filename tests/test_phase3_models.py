"""Tests for Phase 3 identity, workspace governance, and execution-policy models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from core.execution_policy.service import resolve_workspace_execution_profile
from core.identity.service import build_auth_session, build_password_credential, build_user_record
from core.workspaces.models import WorkspaceRecord
from core.workspaces.service import (
    build_workspace_record,
    create_workspace,
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

    def test_identity_models_build_expected_records(self) -> None:
        now = datetime.now(tz=UTC)
        user = build_user_record(user_id="u1", username="piero", now=now, platform_role="admin")
        credential = build_password_credential(user_id="u1", password_hash="hash", algorithm="pbkdf2_sha256", now=now)
        session = build_auth_session(session_id="s1", user_id="u1", expires_at=now + timedelta(hours=1), now=now)

        self.assertEqual(user.platform_role, "admin")
        self.assertEqual(credential.algorithm, "pbkdf2_sha256")
        self.assertEqual(session.status, "active")

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
        default_profile = resolve_workspace_execution_profile("default", requested_mode="full-access")
        isolated_profile = resolve_workspace_execution_profile("acme", requested_mode="full-access")

        self.assertEqual(default_profile.effective_mode, "full-access")
        self.assertEqual(isolated_profile.effective_mode, "sandbox")


if __name__ == "__main__":
    unittest.main()
