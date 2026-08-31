from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.egress.classification import (
    fail_closed_classification,
    validated_classification,
)
from core.runtime.confined_filesystem import (
    ConfinedWorkspaceFilesystem,
    FilesystemResourceObservation,
)
from core.runtime.execution_binding import canonical_digest
from core.runtime.filesystem_mutation_lineage import (
    resolve_filesystem_mutation_lineage,
)
from core.runtime.hosted_agentic_factory import _tool_orchestrator
from core.runtime.hosted_agentic_policy import normalized_tool_result
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.public_content_authority_store import (
    issue_runtime_public_content_authority,
    revoke_runtime_public_content_authority,
)
from core.runtime.tool_catalog import RuntimeToolActorContext
from core.runtime.tool_orchestrator import RuntimeToolConfirmationPolicy
from core.runtime.tool_private_payloads import canonical_tool_arguments
from core.runtime.tool_schema import provider_tool_name
from core.workspaces.data_governance import WorkspaceResourceClassification
from tests.support.hosted_agentic_harness import HostedAgenticHarness


NOW = datetime(2026, 8, 28, tzinfo=UTC)


class _Ledger:
    def __init__(self, records, results, *, artifacts=None, fail_load=False):
        self._records = list(records)
        self._results = dict(results)
        self._artifacts = dict(artifacts or {})
        self._fail_load = fail_load
        for record in self._records:
            result = self._results[record.invocation_id]
            digest = hashlib.sha256(canonical_tool_arguments(result)).hexdigest()
            record.result_source_revision = digest
            record.result_source_digest = digest
            artifact = self._artifacts.get(record.invocation_id)
            if artifact is not None:
                record.result_artifact_sha256 = hashlib.sha256(artifact).hexdigest()
                record.result_artifact_size_bytes = len(artifact)
        self.store = SimpleNamespace(
            list_tool_invocations=self._list_tool_invocations
        )

    def _list_tool_invocations(self, *, session_id):
        return [
            record
            for record in self._records
            if record.session_id == session_id
        ]

    def load_result(self, record):
        if self._fail_load:
            raise RuntimeError("unavailable")
        return self._results[record.invocation_id]

    def load_result_artifact(self, record):
        return self._artifacts[record.invocation_id]


class FilesystemMutationLineageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.observation = FilesystemResourceObservation(
            workspace_id="default",
            resource_kind="filesystem_file",
            resource_ref="notes/public.txt",
            resource_identity="linux:1:2",
            resource_revision="a" * 64,
            resource_digest="a" * 64,
        )
        self.fallback = fail_closed_classification(
            provenance="tool_result",
            source_ref=self.observation.resource_ref,
            source_revision=self.observation.resource_revision,
            source_digest=self.observation.resource_digest,
            resource_identity=self.observation.resource_identity,
        )

    def test_exact_successful_write_rebinds_taint_for_rebuilt_resolver(self) -> None:
        record = self._record(data_class="public")
        resolved = self._resolve(
            self.fallback,
            _Ledger([record], {record.invocation_id: self._result()}),
        )

        self.assertEqual(resolved.data_class, "public")
        self.assertEqual(resolved.source_ref, self.observation.resource_ref)
        self.assertEqual(
            resolved.source_revision,
            self.observation.resource_revision,
        )
        self.assertEqual(
            resolved.resource_identity,
            self.observation.resource_identity,
        )
        self.assertEqual(resolved.classification_revision, 1)

    def test_move_uses_exact_destination_postimage(self) -> None:
        record = self._record(
            handle="core-capability:filesystem.move",
            data_class="workspace_internal",
        )
        result = {
            **self._result(),
            "source_path": "notes/source.txt",
            "destination_path": self.observation.resource_ref,
        }
        result.pop("path")

        resolved = self._resolve(
            self.fallback,
            _Ledger([record], {record.invocation_id: result}),
        )

        self.assertEqual(resolved.data_class, "workspace_internal")

    def test_authoritative_and_lineage_classes_join_restrictively(self) -> None:
        authority = self._classification("public", trust="trusted_actor")
        record = self._record(
            data_class="regulated_or_customer_data",
            trust="untrusted_tool_output",
        )

        resolved = self._resolve(
            authority,
            _Ledger([record], {record.invocation_id: self._result()}),
        )

        self.assertEqual(resolved.data_class, "regulated_or_customer_data")
        self.assertEqual(resolved.trust_level, "untrusted_tool_output")

    def test_incomplete_exact_lineage_cannot_promote_unclassified_resource(self) -> None:
        record = self._record(data_class="public", classification_revision=None)

        resolved = self._resolve(
            self.fallback,
            _Ledger([record], {record.invocation_id: self._result()}),
        )

        self.assertEqual(resolved.data_class, "unclassified")
        self.assertIsNone(resolved.classification_revision)

    def test_compacted_result_uses_verified_original_artifact(self) -> None:
        record = self._record(data_class="public", artifact=True)
        original = json.dumps(self._result()).encode("utf-8")
        ledger = _Ledger(
            [record],
            {record.invocation_id: {"artifact_ref": "private:result"}},
            artifacts={record.invocation_id: original},
        )

        resolved = self._resolve(self.fallback, ledger)

        self.assertEqual(resolved.data_class, "public")

    def test_unreadable_mutation_evidence_fails_closed(self) -> None:
        record = self._record(data_class="public")
        authority = self._classification("public", trust="trusted_actor")

        resolved = self._resolve(
            authority,
            _Ledger(
                [record],
                {record.invocation_id: self._result()},
                fail_load=True,
            ),
        )

        self.assertEqual(resolved.data_class, "unclassified")
        self.assertIsNone(resolved.classification_revision)

    def test_result_digest_mismatch_fails_closed(self) -> None:
        record = self._record(data_class="public")
        ledger = _Ledger([record], {record.invocation_id: self._result()})
        record.result_source_digest = "0" * 64

        resolved = self._resolve(
            self._classification("public", trust="trusted_actor"),
            ledger,
        )

        self.assertEqual(resolved.data_class, "unclassified")
        self.assertIsNone(resolved.classification_revision)

    def _resolve(self, authoritative, ledger):
        return resolve_filesystem_mutation_lineage(
            observation=self.observation,
            provenance="tool_result",
            authoritative=authoritative,
            ledger=ledger,
            session_id="session-1",
        )

    def _record(
        self,
        *,
        handle="core-capability:filesystem.write",
        data_class,
        trust="trusted_actor",
        classification_revision=1,
        artifact=False,
    ):
        return SimpleNamespace(
            invocation_id=f"invocation-{handle}",
            workspace_id="default",
            session_id="session-1",
            state="succeeded",
            resolved_tool_handle=handle,
            result_data_class=data_class,
            result_trust_level=trust,
            result_provenance="tool_result",
            result_classification_revision=classification_revision,
            result_classification_authority_id="",
            result_classification_authority_kind="",
            result_classification_authority_ref="",
            result_classification_authority_revision=None,
            result_classification_authority_digest="",
            result_classification_authority_policy_revision="",
            result_classification_authority_bound=False,
            result_artifact_private_ref=("private:artifact" if artifact else None),
        )

    def _result(self):
        return {
            "path": self.observation.resource_ref,
            "resource_identity": self.observation.resource_identity,
            "resource_revision": self.observation.resource_revision,
            "resource_digest": self.observation.resource_digest,
        }

    def _classification(self, data_class, *, trust):
        return validated_classification(
            data_class=data_class,
            provenance="tool_result",
            trust_level=trust,
            source_ref=self.observation.resource_ref,
            source_revision=self.observation.resource_revision,
            source_digest=self.observation.resource_digest,
            resource_identity=self.observation.resource_identity,
            classification_revision=1,
        )


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
