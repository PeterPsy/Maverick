"""Tests for identity recovery CLI commands."""

from __future__ import annotations

import unittest

from core.cli.errors import CliInvocationNotAllowedError
from core.cli.models import CliInvocationContext
from core.cli.service import run_core_cli_command
from core.identity.errors import UserNotFoundError
from core.identity.service import authenticate_password, bootstrap_default_admin
from core.identity.store import IdentityCollections, IdentityDocumentStore
from core.workspaces.store import WorkspaceCollections, WorkspaceDocumentStore
from tests.support.collections import FakeCollection


class IdentityCliTestCase(unittest.TestCase):
    def make_identity_store(self) -> IdentityDocumentStore:
        return IdentityDocumentStore(
            IdentityCollections(
                users=FakeCollection(),
                credentials=FakeCollection(),
                auth_sessions=FakeCollection(),
            )
        )

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

    def test_reset_admin_password_requires_operator_context(self) -> None:
        identity_store = self.make_identity_store()
        workspace_store = self.make_workspace_store()
        bootstrap_default_admin(identity_store, workspace_store, username="admin", password=None)
        sandbox_context = CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="agent-1",
            effective_mode="sandbox",
        )

        with self.assertRaises(CliInvocationNotAllowedError):
            run_core_cli_command(
                command_id="core.identity.reset-admin-password",
                context=sandbox_context,
                identity_store=identity_store,
                workspace_store=workspace_store,
                arguments={"username": "admin", "password": "new-password"},
            )

    def test_operator_can_set_locked_admin_password_without_returning_plaintext(self) -> None:
        identity_store = self.make_identity_store()
        workspace_store = self.make_workspace_store()
        bootstrap_default_admin(identity_store, workspace_store, username="admin", password=None)
        operator_context = CliInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
        )

        result = run_core_cli_command(
            command_id="core.identity.reset-admin-password",
            context=operator_context,
            identity_store=identity_store,
            workspace_store=workspace_store,
            arguments={"username": "admin", "password": "new-password"},
        )

        self.assertTrue(result["reset"])
        self.assertEqual(result["user"]["username"], "admin")
        self.assertNotIn("new-password", str(result))
        self.assertEqual(authenticate_password(identity_store, username="admin", password="new-password").username, "admin")
        with self.assertRaises(UserNotFoundError):
            authenticate_password(identity_store, username="admin", password="old-password")


if __name__ == "__main__":
    unittest.main()
