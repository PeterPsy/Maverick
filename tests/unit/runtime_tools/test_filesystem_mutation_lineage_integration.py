from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem
from core.runtime.execution_binding import canonical_digest
from core.runtime.hosted_agentic_factory import _tool_orchestrator
from core.runtime.hosted_agentic_policy import normalized_tool_result
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.public_content_authority_store import (
    issue_runtime_public_content_authority,
    revoke_runtime_public_content_authority,
)
from core.runtime.tool_catalog import RuntimeToolActorContext
from core.runtime.tool_orchestrator import RuntimeToolConfirmationPolicy
from core.runtime.tool_schema import provider_tool_name
from core.workspaces.data_governance import WorkspaceResourceClassification
from tests.support.hosted_agentic_harness import HostedAgenticHarness


NOW = datetime(2026, 8, 28, tzinfo=UTC)


class HostedFilesystemMutationLineageIntegrationTest(unittest.TestCase):
    def test_revoked_public_authority_cannot_be_reused_after_rebuild(self) -> None:
        harness = HostedAgenticHarness(self)
        workspace_root = harness.root / "workspaces" / "default"
        (workspace_root / "revoked-lineage.txt").write_text(
            "before\n",
            encoding="utf-8",
        )
        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            state = bootstrap_platform_state(
                start_path=harness.root,
                now=NOW,
                install_builtin_apps=False,
            )
        issued = issue_runtime_public_content_authority(
            state.workspace_store,
            workspace_id="default",
            actor_id="operator-fixture",
            expected_revision=0,
            now=NOW,
        )
        filesystem = ConfinedWorkspaceFilesystem(
            workspace_id="default",
            workspace_root=workspace_root,
        )
        try:
            observation, _classification = filesystem.observe_file(
                "revoked-lineage.txt",
                provenance="tool_result",
            )
        finally:
            filesystem.close()
        actor = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="admin",
            agent_id="chat",
            platform_role="admin",
            workspace_role="owner",
            session_id=harness.session.session_id,
            execution_mode="full-access",
        )
        context = SimpleNamespace(session=harness.session)
        process_registry = HostedToolProcessRegistry(store=state.runtime_store)
        first = _tool_orchestrator(
            context,
            actor=actor,
            state=state,
            ledger=state.runtime_tool_ledger,
            workspace_store=state.workspace_store,
            process_registry=process_registry,
        )
        surfaces = {
            item.definition.handle: item
            for item in first.catalog_builder.core_capabilities
        }
        instructions = surfaces[
            "core-capability:workspace.instructions"
        ].handler({"path": "revoked-lineage.txt"}, actor, None)
        authority = replace(
            harness.authority,
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                filesystem_read=True,
                filesystem_write=True,
            ),
            allowed_tool_handles=(
                "core-capability:filesystem.read",
                "core-capability:filesystem.write",
            ),
            allowed_remote_data_classes=("public",),
            authority_digest="",
        )
        authority = replace(authority, authority_digest=canonical_digest(authority))
        policy = RuntimeToolConfirmationPolicy(
            policy_revision="revoked-lineage:1",
            require_confirmation_for_mutating=False,
            require_confirmation_for_destructive=False,
            max_tool_result_bytes=262_144,
        )
        written = first.invoke_provider_tool(
            provider_tool_name=provider_tool_name(
                "core-capability:filesystem.write"
            ),
            provider_tool_call_id="call-revoked-lineage-write",
            arguments={
                "path": "revoked-lineage.txt",
                "content": "after\n",
                "replace_only": True,
                "expected_resource_identity": observation.resource_identity,
                "expected_resource_revision": observation.resource_revision,
                "instruction_scope_digest": instructions.payload["scope_digest"],
            },
            authority=authority,
            context=actor,
            turn_id="turn-revoked-lineage",
            policy=policy,
        )
        self.assertEqual(written.invocation.result_data_class, "public")
        self.assertEqual(
            written.invocation.result_classification_authority_id,
            issued.classification_id,
        )

        revoke_runtime_public_content_authority(
            state.workspace_store,
            workspace_id="default",
            actor_id="operator-fixture",
            expected_revision=issued.revision,
            reason="negative lineage probe",
            now=NOW,
        )
        rebuilt = _tool_orchestrator(
            context,
            actor=actor,
            state=state,
            ledger=state.runtime_tool_ledger,
            workspace_store=state.workspace_store,
            process_registry=process_registry,
        )
        reread = rebuilt.invoke_provider_tool(
            provider_tool_name=provider_tool_name(
                "core-capability:filesystem.read"
            ),
            provider_tool_call_id="call-revoked-lineage-read",
            arguments={"path": "revoked-lineage.txt"},
            authority=authority,
            context=actor,
            turn_id="turn-revoked-lineage",
            policy=policy,
        )

        self.assertEqual(reread.invocation.state, "succeeded")
        self.assertEqual(reread.invocation.result_data_class, "unclassified")
        normalized, is_error = normalized_tool_result(
            rebuilt,
            reread,
            allowed_remote_data_classes=("public",),
        )
        self.assertTrue(is_error)
        self.assertEqual(normalized, {"error": "tool_result_egress_denied"})

    def test_rebuilt_orchestrator_preserves_exact_read_after_write_taint(self) -> None:
        harness = HostedAgenticHarness(self)
        workspace_root = harness.root / "workspaces" / "default"
        (workspace_root / "lineage.txt").write_text("before\n", encoding="utf-8")
        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            state = bootstrap_platform_state(
                start_path=harness.root,
                now=NOW,
                install_builtin_apps=False,
            )
        filesystem = ConfinedWorkspaceFilesystem(
            workspace_id="default",
            workspace_root=workspace_root,
        )
        try:
            observation, _classification = filesystem.observe_file(
                "lineage.txt",
                provenance="tool_result",
            )
        finally:
            filesystem.close()
        state.workspace_store.save_resource_classification(
            WorkspaceResourceClassification(
                classification_id="classification-lineage-1",
                workspace_id=observation.workspace_id,
                resource_kind=observation.resource_kind,
                resource_ref=observation.resource_ref,
                resource_identity=observation.resource_identity,
                resource_revision=observation.resource_revision,
                resource_digest=observation.resource_digest,
                data_class="public",
                trust_level="trusted_actor",
                revision=1,
                classified_by_actor_id="fixture-classifier",
                classified_at=NOW,
                updated_at=NOW,
            ),
            expected_revision=0,
        )
        actor = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="admin",
            agent_id="chat",
            platform_role="admin",
            workspace_role="owner",
            session_id=harness.session.session_id,
            execution_mode="full-access",
        )
        context = SimpleNamespace(session=harness.session)
        process_registry = HostedToolProcessRegistry(store=state.runtime_store)
        first = _tool_orchestrator(
            context,
            actor=actor,
            state=state,
            ledger=state.runtime_tool_ledger,
            workspace_store=state.workspace_store,
            process_registry=process_registry,
        )
        surfaces = {
            item.definition.handle: item
            for item in first.catalog_builder.core_capabilities
        }
        instructions = surfaces[
            "core-capability:workspace.instructions"
        ].handler({"path": "lineage.txt"}, actor, None)
        authority = replace(
            harness.authority,
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                filesystem_read=True,
                filesystem_write=True,
            ),
            allowed_tool_handles=(
                "core-capability:filesystem.read",
                "core-capability:filesystem.write",
            ),
            authority_digest="",
        )
        authority = replace(
            authority,
            authority_digest=canonical_digest(authority),
        )
        policy = RuntimeToolConfirmationPolicy(
            policy_revision="lineage:1",
            require_confirmation_for_mutating=False,
            require_confirmation_for_destructive=False,
            max_tool_result_bytes=262_144,
        )
        written = first.invoke_provider_tool(
            provider_tool_name=provider_tool_name(
                "core-capability:filesystem.write"
            ),
            provider_tool_call_id="call-lineage-write",
            arguments={
                "path": "lineage.txt",
                "content": "after\n",
                "replace_only": True,
                "expected_resource_identity": observation.resource_identity,
                "expected_resource_revision": observation.resource_revision,
                "instruction_scope_digest": instructions.payload["scope_digest"],
            },
            authority=authority,
            context=actor,
            turn_id="turn-lineage",
            policy=policy,
        )
        self.assertEqual(written.invocation.state, "succeeded")
        self.assertEqual(written.invocation.result_data_class, "public")

        rebuilt = _tool_orchestrator(
            context,
            actor=actor,
            state=state,
            ledger=state.runtime_tool_ledger,
            workspace_store=state.workspace_store,
            process_registry=process_registry,
        )
        reread = rebuilt.invoke_provider_tool(
            provider_tool_name=provider_tool_name(
                "core-capability:filesystem.read"
            ),
            provider_tool_call_id="call-lineage-read",
            arguments={"path": "lineage.txt"},
            authority=authority,
            context=actor,
            turn_id="turn-lineage",
            policy=policy,
        )

        self.assertEqual(reread.invocation.state, "succeeded")
        self.assertEqual(reread.invocation.result_data_class, "public")
        self.assertEqual(
            state.runtime_tool_ledger.load_result(reread.invocation)["content"],
            "after\n",
        )


if __name__ == "__main__":
    unittest.main()
