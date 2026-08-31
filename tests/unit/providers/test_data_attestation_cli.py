"""Operator-only CLI tests for workspace data attestations."""

from __future__ import annotations

import unittest

from core.cli.models import CliInvocationContext
from core.cli.runtime_provider_commands import runtime_provider_command_specs
from core.workspaces.store import WorkspaceCollections, WorkspaceDocumentStore
from tests.support.collections import FakeCollection


class DataAttestationCliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.store = WorkspaceDocumentStore(
            WorkspaceCollections(
                workspaces=FakeCollection(),
                memberships=FakeCollection(),
                governance=FakeCollection(),
                quotas=FakeCollection(),
                active_workspace_selections=FakeCollection(),
                data_attestations=FakeCollection(),
                resource_classifications=FakeCollection(),
                data_governance_audits=FakeCollection(),
            )
        )
        self.handlers = {
            definition.command_id: handler
            for definition, handler in runtime_provider_command_specs(workspace_store=self.store)
        }
        self.definitions = {
            definition.command_id: definition
            for definition, _ in runtime_provider_command_specs(workspace_store=self.store)
        }
        self.context = CliInvocationContext(
            caller_kind="operator",
            workspace_id="workspace-1",
            agent_id=None,
            effective_mode=None,
            platform_role="admin",
            user_id="operator-user-1",
            workspace_role="admin",
        )

    def test_issue_status_and_revoke_use_trusted_context_actor(self) -> None:
        issued = self.handlers["core.providers.agentic.attestation.issue"](
            {
                "scope_type": "workspace",
                "expected_revision": 0,
                "confirmation": "fake-data-scope-reviewed",
            },
            self.context,
        )
        status = self.handlers["core.providers.agentic.attestation.status"]({}, self.context)
        revoked = self.handlers["core.providers.agentic.attestation.revoke"](
            {"expected_revision": 1, "reason": "no longer a fixture workspace"},
            self.context,
        )

        self.assertEqual(issued["attestation"]["state"], "active")
        self.assertEqual(status["attestation"]["state"], "active")
        self.assertEqual(revoked["attestation"]["state"], "revoked")
        persisted = self.store.get_data_attestation("workspace-1")
        assert persisted is not None
        self.assertEqual(persisted.attested_by_actor_id, "operator-user-1")
        self.assertEqual(persisted.revoked_by_actor_id, "operator-user-1")

    def test_browser_style_actor_argument_is_not_in_schema_or_handler_authority(self) -> None:
        definition = self.definitions["core.providers.agentic.attestation.issue"]

        self.assertNotIn("actor_id", definition.argument_schema["properties"])
        result = self.handlers["core.providers.agentic.attestation.issue"](
            {
                "actor_id": "browser-forged",
                "scope_type": "workspace",
                "expected_revision": 0,
                "confirmation": "fake-data-scope-reviewed",
            },
            self.context,
        )
        persisted = self.store.get_data_attestation("workspace-1")
        self.assertNotIn("error", result)
        assert persisted is not None
        self.assertEqual(persisted.attested_by_actor_id, "operator-user-1")

    def test_mutation_requires_operator_identity_and_confirmation(self) -> None:
        no_actor = CliInvocationContext(
            caller_kind="operator",
            workspace_id="workspace-1",
            agent_id=None,
            effective_mode=None,
            platform_role="admin",
        )

        self.assertEqual(
            self.handlers["core.providers.agentic.attestation.issue"](
                {"scope_type": "workspace", "expected_revision": 0},
                self.context,
            )["error"],
            "attestation_confirmation_required",
        )
        self.assertEqual(
            self.handlers["core.providers.agentic.attestation.issue"](
                {
                    "scope_type": "workspace",
                    "expected_revision": 0,
                    "confirmation": "fake-data-scope-reviewed",
                },
                no_actor,
            )["error"],
            "operator_actor_required",
        )

    def test_public_content_authority_is_operator_owned_and_revocable(self) -> None:
        issue_definition = self.definitions[
            "core.providers.agentic.public-content.issue"
        ]
        self.assertNotIn("actor_id", issue_definition.argument_schema["properties"])

        missing_confirmation = self.handlers[
            "core.providers.agentic.public-content.issue"
        ](
            {"expected_revision": 0},
            self.context,
        )
        issued = self.handlers["core.providers.agentic.public-content.issue"](
            {
                "expected_revision": 0,
                "confirmation": "public-workspace-content-reviewed",
                "actor_id": "browser-forged",
            },
            self.context,
        )
        status = self.handlers["core.providers.agentic.public-content.status"](
            {},
            self.context,
        )
        revoked = self.handlers[
            "core.providers.agentic.public-content.revoke"
        ](
            {"expected_revision": 1, "reason": "approval withdrawn"},
            self.context,
        )
        revoked_status = self.handlers[
            "core.providers.agentic.public-content.status"
        ]({}, self.context)

        self.assertEqual(
            missing_confirmation["error"],
            "runtime_public_content_authority_confirmation_required",
        )
        self.assertTrue(
            issued["public_content_authority"]["authoritative"]
        )
        self.assertEqual(
            len(issued["public_content_authority"]["authority_digest"]),
            64,
        )
        self.assertEqual(status["public_content_authority"]["state"], "active")
        self.assertEqual(
            revoked["public_content_authority"]["state"],
            "revoked",
        )
        self.assertEqual(
            revoked_status["public_content_authority"]["state"],
            "revoked",
        )


if __name__ == "__main__":
    unittest.main()
