from __future__ import annotations

import base64
from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile
import unittest

from core.egress.classification import validated_classification
from core.cli.models import CliCommandDefinition, CliInvocationPolicy
from core.runtime.tool_catalog import RuntimeToolCatalogBuilder
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_orchestrator import RuntimeToolOrchestrator
from core.runtime.tool_result_artifacts import (
    MAX_ARTIFACT_READ_BYTES,
    MAX_ARTIFACT_READ_PROVIDER_RESULT_BYTES,
    TOOL_RESULT_ARTIFACT_READ_HANDLE,
    build_tool_result_artifact_capabilities,
    project_hosted_tool_result,
)
from core.runtime.tool_schema import provider_tool_name
from core.runtime.hosted_harness_recipes import hosted_full_context_policy
from tests.support.cases.tool_orchestrator import _RuntimeToolOrchestratorFixture


NOW = datetime(2026, 8, 16, tzinfo=UTC)

OBJECT_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}


class RuntimeToolOrchestratorTest(_RuntimeToolOrchestratorFixture, unittest.TestCase):
    def test_shell_output_never_downgrades_classified_workspace_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "confidential.txt").write_text(
                "internal-only",
                encoding="utf-8",
            )

            def classify(observation, provenance):
                return validated_classification(
                    data_class="workspace_internal",
                    provenance=provenance,
                    trust_level="untrusted_tool_output",
                    source_ref=observation.resource_ref,
                    source_revision=observation.resource_revision,
                    source_digest=observation.resource_digest,
                    resource_identity=observation.resource_identity,
                    classification_revision=1,
                )

            orchestrator = RuntimeToolOrchestrator(
                catalog_builder=RuntimeToolCatalogBuilder(
                    cli_registry=self.cli_registry,
                    mcp_registry=self.mcp_registry,
                    core_capabilities=build_core_runtime_tool_capabilities(
                        workspace_id="default",
                        workspace_root=root,
                        runtime_root=root / "runtime",
                        resource_classification_resolver=classify,
                    ),
                ),
                ledger=self.ledger,
            )
            authority = replace(
                self.authority,
                allowed_capabilities=replace(
                    self.authority.allowed_capabilities,
                    filesystem_read=True,
                    shell=True,
                ),
                allowed_tool_handles=(
                    "core-capability:filesystem.read",
                    "core-capability:shell.run",
                ),
                execution_mode="full-access",
            )
            context = replace(self.context, execution_mode="full-access")
            policy = replace(
                self.policy,
                require_confirmation_for_destructive=False,
            )

            filesystem_read = orchestrator.invoke_provider_tool(
                provider_tool_name=provider_tool_name(
                    "core-capability:filesystem.read"
                ),
                provider_tool_call_id="call-classified-read",
                arguments={"path": "confidential.txt"},
                authority=authority,
                context=context,
                turn_id="turn-tools",
                policy=policy,
            )
            shell_read = orchestrator.invoke_provider_tool(
                provider_tool_name=provider_tool_name(
                    "core-capability:shell.run"
                ),
                provider_tool_call_id="call-unclassified-shell-read",
                arguments={
                    "argv": [
                        "/bin/cat",
                        "/workspace/confidential.txt",
                    ],
                    "mutation_scopes": [],
                },
                authority=authority,
                context=context,
                turn_id="turn-tools",
                policy=policy,
            )

            self.assertEqual(
                filesystem_read.invocation.result_data_class,
                "workspace_internal",
            )
            self.assertEqual(
                shell_read.invocation.result_data_class,
                "unclassified",
            )

    def test_large_result_keeps_original_artifact_and_exposes_bounded_chunks(self) -> None:
        original = {"blob": "line of bounded synthetic output\n" * 1_000}
        self.cli_registry.register_command(
            CliCommandDefinition(
                command_id="fixture.large",
                path_segments=["fixture", "large"],
                description="Return a large synthetic fixture.",
                argument_schema=OBJECT_SCHEMA,
                owner_kind="core",
                owner_id="test",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(
                    False,
                    None,
                    True,
                    True,
                    False,
                ),
                entrypoint_path=None,
                effect_class="read",
                safe_to_retry=True,
                schema_public=True,
                certified_tcb_component="tool-schema-catalog",
            ),
            lambda _arguments, _context: original,
        )
        authority = replace(
            self.authority,
            allowed_tool_handles=(
                *self.authority.allowed_tool_handles,
                "cli:fixture.large",
            ),
        )
        outcome = self.orchestrator.invoke_provider_tool(
            provider_tool_name=provider_tool_name("cli:fixture.large"),
            provider_tool_call_id="call-large-artifact",
            arguments={"value": 1},
            authority=authority,
            context=self.context,
            turn_id="turn-tools",
            policy=replace(self.policy, max_tool_result_bytes=100_000),
        )

        invocation = outcome.invocation
        original_bytes = json.dumps(
            original,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        self.assertTrue(invocation.result_artifact_private_ref)
        self.assertEqual(invocation.result_artifact_size_bytes, len(original_bytes))
        self.assertEqual(self.ledger.load_result_artifact(invocation), original_bytes)
        with self.assertRaisesRegex(
            RuntimeToolError,
            "tool_private_payload_integrity_failed",
        ):
            self.ledger.load_result_artifact(
                replace(invocation, result_artifact_sha256="0" * 64)
            )
        self.assertNotEqual(self.ledger.load_result(invocation), original)

        projection = project_hosted_tool_result(
            self.ledger.load_result(invocation),
            invocation=invocation,
            context_policy=hosted_full_context_policy(),
        )
        self.assertEqual(
            projection["artifact_ref"],
            f"runtime-tool-result:{invocation.result_id}",
        )
        self.assertEqual(projection["artifact_bytes"], len(original_bytes))
        self.assertEqual(
            projection["artifact_sha256"],
            invocation.result_artifact_sha256,
        )
        self.assertLessEqual(
            len(json.dumps(projection, separators=(",", ":"), sort_keys=True).encode()),
            hosted_full_context_policy().tool_result_summary_bytes,
        )
        oversized_field_name = "field-" + "x" * 100_000
        adversarial_projection = project_hosted_tool_result(
            {oversized_field_name: "value"},
            invocation=replace(
                invocation,
                result_artifact_private_ref=None,
                result_artifact_sha256="",
                result_artifact_size_bytes=None,
            ),
            context_policy=hosted_full_context_policy(),
        )
        adversarial_encoded = json.dumps(
            adversarial_projection,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        self.assertLessEqual(
            len(adversarial_encoded),
            hosted_full_context_policy().tool_result_summary_bytes,
        )
        self.assertNotIn(oversized_field_name.encode(), adversarial_encoded)

        surface = build_tool_result_artifact_capabilities(
            ledger=self.ledger,
            workspace_id="default",
        )[0]
        first = surface.handler(
            {
                "artifact_ref": projection["artifact_ref"],
                "offset": 0,
                "max_bytes": 128,
            },
            self.context,
            None,
        )
        self.assertEqual(
            base64.b64decode(first.payload["content"]),
            original_bytes[:128],
        )
        self.assertTrue(first.payload["has_more"])
        largest = surface.handler(
            {
                "artifact_ref": projection["artifact_ref"],
                "offset": 0,
                "max_bytes": MAX_ARTIFACT_READ_BYTES,
            },
            self.context,
            None,
        )
        largest_encoded = json.dumps(
            largest.payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        self.assertGreater(
            len(largest_encoded),
            hosted_full_context_policy().tool_result_inline_bytes,
        )
        self.assertLessEqual(
            len(largest_encoded),
            MAX_ARTIFACT_READ_PROVIDER_RESULT_BYTES,
        )
        self.assertEqual(
            project_hosted_tool_result(
                largest.payload,
                invocation=replace(
                    invocation,
                    resolved_tool_handle="core-capability:artifact.read",
                ),
                context_policy=hosted_full_context_policy(),
            ),
            largest.payload,
        )
        artifact_orchestrator = RuntimeToolOrchestrator(
            catalog_builder=RuntimeToolCatalogBuilder(
                cli_registry=self.cli_registry,
                mcp_registry=self.mcp_registry,
                core_capabilities=(surface,),
            ),
            ledger=self.ledger,
        )
        artifact_authority = replace(
            self.authority,
            allowed_capabilities=replace(
                self.authority.allowed_capabilities,
                filesystem_read=True,
            ),
            allowed_tool_handles=(TOOL_RESULT_ARTIFACT_READ_HANDLE,),
        )
        artifact_outcome = artifact_orchestrator.invoke_provider_tool(
            provider_tool_name=provider_tool_name(
                TOOL_RESULT_ARTIFACT_READ_HANDLE
            ),
            provider_tool_call_id="call-read-large-artifact",
            arguments={
                "artifact_ref": projection["artifact_ref"],
                "offset": 0,
                "max_bytes": MAX_ARTIFACT_READ_BYTES,
            },
            authority=artifact_authority,
            context=self.context,
            turn_id="turn-tools",
            policy=replace(self.policy, max_tool_result_bytes=100_000),
        )
        persisted_chunk = self.ledger.load_result(artifact_outcome.invocation)
        self.assertEqual(persisted_chunk, largest.payload)
        self.assertIsNone(
            artifact_outcome.invocation.result_artifact_private_ref
        )
        self.assertEqual(
            project_hosted_tool_result(
                persisted_chunk,
                invocation=artifact_outcome.invocation,
                context_policy=hosted_full_context_policy(),
            ),
            largest.payload,
        )
        with self.assertRaisesRegex(
            RuntimeToolError,
            "tool_result_artifact_not_found",
        ):
            surface.handler(
                {"artifact_ref": projection["artifact_ref"]},
                replace(self.context, session_id="another-session"),
                None,
            )


if __name__ == "__main__":
    unittest.main()
