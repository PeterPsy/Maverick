from __future__ import annotations

import json
from types import SimpleNamespace
import unittest

from core.cli.command_registry import CliCommandRegistry
from core.cli.models import CliCommandDefinition, CliInvocationPolicy
from core.egress.classification import (
    content_sha256,
    validated_classification,
)
from core.mcp.tool_registry import McpToolRegistry
from core.mcp.models import McpInvocationPolicy, McpToolDefinition
from core.runtime.hosted_tool_result_admission import (
    build_hosted_tool_result_admission_resolver,
    build_hosted_tool_result_preflight_resolver,
)
from core.runtime.hosted_agentic_tool_results import (
    make_agentic_tool_result,
    pairing_safe_tool_result,
)
from core.runtime.tool_catalog import (
    RuntimeToolActorContext,
    RuntimeToolSurfaceResult,
)
from core.runtime.tool_full_workspace_support import commit_text_change
from core.shared.tool_effects import ToolArgumentEffectMap


class HostedToolResultAdmissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = CliCommandRegistry()
        self.mcp = McpToolRegistry()
        self.actor = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="user-1",
            agent_id="chat",
            platform_role="admin",
            workspace_role="owner",
            session_id="session-hosted",
            execution_mode="full-access",
        )
        self.resolve = build_hosted_tool_result_admission_resolver(
            cli_registry=self.cli,
            mcp_registry=self.mcp,
        )

    def test_shell_and_process_output_are_complete_and_content_classified(
        self,
    ) -> None:
        shell = self.resolve(
            "core-capability:shell.run",
            {"argv": ["fixture"]},
            {
                "exit_code": 0,
                "output": "customer SSN 123-45-6789 must stay private",
                "output_bytes": 33,
                "stream_complete": True,
                "workspace_effects_committed": True,
                "workspace_effect_count": 0,
                "workspace_effect_paths": ("secret.txt",),
                "mutation_scope_count": 0,
            },
            self.actor,
        )
        self.assertIsInstance(shell, RuntimeToolSurfaceResult)
        self.assertEqual(shell.classification.data_class, "regulated_or_customer_data")
        self.assertIn("123-45-6789", shell.payload["output"])
        self._assert_digest_matches(shell)

        status = self.resolve(
            "core-capability:process.status",
            {"process_id": "agent-process-1"},
            {
                "process_id": "agent-process-1",
                "status": "running",
                "exit_code": None,
                "output": "ordinary process output",
                "output_offset": 0,
                "next_output_offset": 14,
                "output_pending": False,
                "stdin_open": True,
                "failure_reason": None,
                "output_truncated": False,
                "workspace_effects": {"workspace_effect_paths": ["secret.txt"]},
            },
            self.actor,
        )
        self.assertIsInstance(status, RuntimeToolSurfaceResult)
        self.assertEqual(status.classification.data_class, "unclassified")
        self.assertEqual(status.payload["output"], "ordinary process output")
        self._assert_digest_matches(status)

    def test_process_start_identifier_survives_as_bounded_action_metadata(
        self,
    ) -> None:
        started = self.resolve(
            "core-capability:process.start",
            {"argv": ["fixture"]},
            {
                "process_id": "agent-process-1",
                "status": "running",
                "output_offset": 0,
                "workspace_effects_pending": True,
                "mutation_scope_count": 1,
                "raw_output": "must not be admitted",
            },
            self.actor,
        )

        self.assertIsInstance(started, RuntimeToolSurfaceResult)
        self.assertEqual(started.classification.data_class, "public")
        self.assertEqual(started.payload["process_id"], "agent-process-1")
        self.assertNotIn("raw_output", started.payload)
        self._assert_digest_matches(started)

    def test_edit_diff_retains_exact_taint_rebound_to_postimage(
        self,
    ) -> None:
        source = validated_classification(
            data_class="public",
            provenance="tool_result",
            trust_level="untrusted_tool_output",
            source_ref="workspace:fixture.txt",
            source_revision="preimage-1",
            source_digest="c" * 64,
            resource_identity="workspace-file:fixture.txt",
            classification_revision=1,
        )
        postimage = validated_classification(
            data_class="public",
            provenance="tool_result",
            trust_level="untrusted_tool_output",
            source_ref="fixture.txt",
            source_revision="postimage-2",
            source_digest="d" * 64,
            resource_identity="workspace-file:fixture.txt",
            classification_revision=1,
        )
        filesystem = SimpleNamespace(
            write_text=lambda *_args, **_kwargs: RuntimeToolSurfaceResult(
                {"path": "fixture.txt", "resource_revision": "postimage-2"},
                postimage,
            )
        )

        result = commit_text_change(
            filesystem,
            path="fixture.txt",
            before="before\n",
            after="after\n",
            expected_identity="workspace-file:fixture.txt",
            expected_revision="preimage-1",
            evidence={"instruction_scope_digest": "d" * 64},
            mutation_guard=SimpleNamespace(),
            operation_count=1,
        )

        self.assertIs(result.classification, postimage)
        self.assertEqual(result.classification.data_class, source.data_class)
        self.assertNotEqual(
            result.classification.source_revision,
            source.source_revision,
        )
        self.assertIn("-before", result.payload["diff"])
        self.assertIn("+after", result.payload["diff"])

    def test_core_result_is_classified_from_bytes_not_ownership_declaration(
        self,
    ) -> None:
        self.cli.register_command(
            CliCommandDefinition(
                command_id="core.undeclared",
                path_segments=["core", "undeclared"],
                description="Core result without an egress declaration.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="fixture-core",
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
                schema_public=True,
                certified_tcb_component="tool-schema-catalog",
            ),
            lambda _arguments, _context: {},
        )
        resolved = self.resolve(
            "core-capability:cli.run",
            {"command_id": "core.undeclared"},
            {"secret": "not covered by the public schema declaration"},
            self.actor,
        )

        self.assertIsInstance(resolved, RuntimeToolSurfaceResult)
        self.assertEqual(resolved.classification.data_class, "credential_or_secret")
        self.assertEqual(
            pairing_safe_tool_result(
                resolved.payload,
                is_error=False,
                result_data_class=resolved.classification.data_class,
                allowed_remote_data_classes=("public",),
            ),
            ({"error": "tool_result_egress_denied"}, True),
        )

    def test_app_result_claim_cannot_promote_untrusted_cli_bytes(self) -> None:
        self.cli.register_command(
            CliCommandDefinition(
                command_id="app.claimed-public",
                path_segments=["app", "claimed-public"],
                description="Untrusted app fixture.",
                argument_schema={"type": "object"},
                owner_kind="app",
                owner_id="fixture-app",
                workspace_id="default",
                exposure_scope="workspace_enabled_app",
                invocation_policy=CliInvocationPolicy(
                    False,
                    None,
                    True,
                    True,
                    False,
                ),
                entrypoint_path="apps/fixture/cli.py",
                effect_class="read",
                schema_public=True,
                certified_tcb_component="tool-schema-catalog",
                agentic_result_data_class="public",
            ),
            lambda _arguments, _context: {},
        )

        resolved = self.resolve(
            "core-capability:cli.run",
            {"command_id": "app.claimed-public"},
            {"secret": "must not be promoted"},
            self.actor,
        )

        self.assertIsInstance(resolved, RuntimeToolSurfaceResult)
        self.assertEqual(resolved.classification.data_class, "credential_or_secret")

    def test_app_cli_and_mcp_discovery_is_never_silently_filtered(self) -> None:
        self.cli.register_command(
            CliCommandDefinition(
                command_id="app.visible",
                path_segments=["app", "visible"],
                description="Workspace app command.",
                argument_schema={"type": "object"},
                owner_kind="app",
                owner_id="fixture-app",
                workspace_id="default",
                exposure_scope="workspace_enabled_app",
                invocation_policy=CliInvocationPolicy(
                    False,
                    None,
                    True,
                    True,
                    False,
                ),
                entrypoint_path="apps/fixture/cli.py",
                effect_class="read",
                schema_public=True,
                certified_tcb_component="tool-schema-catalog",
            ),
            lambda _arguments, _context: {},
        )
        self.mcp.register_tool(
            McpToolDefinition(
                tool_name="app_visible",
                description="Workspace app tool.",
                input_schema={"type": "object"},
                output_schema=None,
                owner_kind="app",
                owner_id="fixture-app",
                workspace_id="default",
                exposure_scope="workspace_enabled_app",
                invocation_policy=McpInvocationPolicy(
                    False,
                    True,
                    True,
                    False,
                ),
                entrypoint_path="apps/fixture/mcp.py",
                effect_class="read",
                schema_public=True,
                certified_tcb_component="tool-schema-catalog",
            ),
            lambda _arguments, _context: {},
        )
        cli_payload = {
            "registry_revision": "fixture",
            "commands": [{"command_id": "app.visible", "owner_kind": "app"}],
            "next_cursor": None,
            "discovery_first": True,
        }
        mcp_payload = {
            "registry_revision": "fixture",
            "tools": [{"tool_name": "app_visible", "owner_kind": "app"}],
            "next_cursor": None,
            "discovery_first": True,
        }

        cli_result = self.resolve(
            "core-capability:cli.list",
            {},
            cli_payload,
            self.actor,
        )
        mcp_result = self.resolve(
            "core-capability:mcp.list",
            {},
            mcp_payload,
            self.actor,
        )
        self.assertIsInstance(cli_result, RuntimeToolSurfaceResult)
        self.assertIsInstance(mcp_result, RuntimeToolSurfaceResult)
        self.assertEqual(cli_result.payload, cli_payload)
        self.assertEqual(mcp_result.payload, mcp_payload)
        self.assertEqual(cli_result.classification.data_class, "unclassified")
        self.assertEqual(mcp_result.classification.data_class, "unclassified")
        self.assertEqual(cli_payload["commands"][0]["command_id"], "app.visible")
        self.assertEqual(mcp_payload["tools"][0]["tool_name"], "app_visible")

    def test_preflight_denies_unguaranteed_effects_before_execution(self) -> None:
        self.cli.register_command(
            CliCommandDefinition(
                command_id="app.mutate",
                path_segments=["app", "mutate"],
                description="Mutating app command.",
                argument_schema={"type": "object"},
                owner_kind="app",
                owner_id="fixture-app",
                workspace_id="default",
                exposure_scope="workspace_enabled_app",
                invocation_policy=CliInvocationPolicy(False, None, True, True, False),
                entrypoint_path="apps/fixture/cli.py",
                effect_class="mutating",
                schema_public=True,
            ),
            lambda _arguments, _context: {},
        )
        self.cli.register_command(
            CliCommandDefinition(
                command_id="app.mixed",
                path_segments=["app", "mixed"],
                description="Argument-sensitive app command.",
                argument_schema={"type": "object"},
                owner_kind="app",
                owner_id="fixture-app",
                workspace_id="default",
                exposure_scope="workspace_enabled_app",
                invocation_policy=CliInvocationPolicy(False, None, True, True, False),
                entrypoint_path="apps/fixture/cli.py",
                effect_class="mutating",
                argument_effects=ToolArgumentEffectMap(
                    argument_name="action",
                    omitted_effect_class="read",
                    value_effect_classes=(("catalog", "read"), ("write", "mutating")),
                ),
            ),
            lambda _arguments, _context: {},
        )
        preflight = build_hosted_tool_result_preflight_resolver(
            cli_registry=self.cli,
            mcp_registry=self.mcp,
        )

        self.assertFalse(
            preflight(
                "core-capability:shell.run",
                {"mutation_scopes": [{"path": "."}]},
                self.actor,
            ).admitted_before_effect
        )
        self.assertTrue(
            preflight(
                "core-capability:cli.run",
                {"command_id": "app.mixed", "arguments": {"action": "catalog"}},
                self.actor,
            ).admitted_before_effect
        )
        for nested in ({"action": "write"}, {"action": "unknown"}, "malformed"):
            with self.subTest(nested=nested):
                self.assertFalse(
                    preflight(
                        "core-capability:cli.run",
                        {"command_id": "app.mixed", "arguments": nested},
                        self.actor,
                    ).admitted_before_effect
                )
        self.assertTrue(
            preflight(
                "core-capability:shell.run",
                {"mutation_scopes": []},
                self.actor,
            ).admitted_before_effect
        )
        self.assertFalse(
            preflight(
                "core-capability:cli.run",
                {"command_id": "app.mutate"},
                self.actor,
            ).admitted_before_effect
        )

    def test_unknown_resource_result_keeps_its_existing_fail_closed_taint(self) -> None:
        self.assertIsNone(
            self.resolve(
                "core-capability:filesystem.read",
                {"path": "fixture.txt"},
                {"content": "not governed"},
                self.actor,
            )
        )

    def test_artifact_projection_binds_semantic_digest_to_projected_bytes(
        self,
    ) -> None:
        original_digest = "a" * 64
        projected = {
            "artifact_ref": "runtime-tool-result:result-1",
            "artifact_bytes": 20_000,
            "artifact_sha256": "b" * 64,
            "projected": True,
        }
        invocation = SimpleNamespace(
            result_source_digest=original_digest,
            result_data_class="public",
            result_trust_level="untrusted_tool_output",
            result_provenance="tool_result",
            result_source_ref="core-hosted-tool-result:fixture",
            result_source_revision="1",
            result_resource_identity="fixture:result-1",
            result_classification_revision=1,
        )

        provider_result = make_agentic_tool_result(
            provider_tool_call_id="call-large-artifact",
            provider_tool_name="mav_fixture_large",
            result=projected,
            is_error=False,
            invocation=invocation,
        )

        self.assertEqual(
            provider_result.source_metadata.source_block_digest,
            content_sha256(provider_result.content),
        )
        self.assertNotEqual(
            provider_result.source_metadata.source_block_digest,
            original_digest,
        )
        self.assertEqual(
            provider_result.source_metadata.source_data_class,
            "public",
        )

    def _assert_digest_matches(self, result: RuntimeToolSurfaceResult) -> None:
        encoded = json.dumps(
            result.payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self.assertEqual(
            result.classification.source_digest,
            content_sha256(encoded),
        )


if __name__ == "__main__":
    unittest.main()
