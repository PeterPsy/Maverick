from __future__ import annotations

from datetime import UTC, datetime
import json
import unittest

from core.cli.command_registry import CliCommandRegistry
from core.cli.models import CliCommandDefinition, CliInvocationPolicy
from core.egress.classification import content_sha256
from core.mcp.tool_registry import McpToolRegistry
from core.runtime.hosted_tool_result_admission import (
    build_hosted_tool_result_admission_resolver,
    build_hosted_tool_result_preflight_resolver,
)
from core.runtime.public_content_authority import (
    build_runtime_public_content_authority_record,
)
from core.runtime.tool_catalog import RuntimeToolActorContext, RuntimeToolSurfaceResult


class HostedToolResultPublicAuthorityTest(unittest.TestCase):
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

    def test_operator_authority_classifies_exact_ordinary_output_public(self) -> None:
        authority = build_runtime_public_content_authority_record(
            workspace_id="default",
            actor_id="operator-1",
            active=True,
            now=datetime(2026, 8, 31, tzinfo=UTC),
        )
        resolve = build_hosted_tool_result_admission_resolver(
            cli_registry=self.cli,
            mcp_registry=self.mcp,
            public_content_authority_resolver=lambda workspace_id: (
                authority if workspace_id == "default" else None
            ),
        )

        ordinary = resolve(
            "core-capability:shell.run",
            {"argv": ["printf", "public output"]},
            {"exit_code": 0, "output": "ordinary public output"},
            self.actor,
        )
        sensitive = resolve(
            "core-capability:shell.run",
            {"argv": ["printf", "sensitive"]},
            {"exit_code": 0, "output": "customer SSN 123-45-6789"},
            self.actor,
        )

        self.assertEqual(ordinary.classification.data_class, "public")
        self.assertEqual(
            ordinary.classification.classification_revision,
            authority.revision,
        )
        self.assertIn(authority.resource_digest, ordinary.classification.source_ref)
        self.assertEqual(
            sensitive.classification.data_class,
            "regulated_or_customer_data",
        )
        self._assert_digest_matches(ordinary)

    def test_certified_core_result_contract_is_an_explicit_public_authority(
        self,
    ) -> None:
        self.cli.register_command(
            CliCommandDefinition(
                command_id="core.public-result",
                path_segments=["core", "public-result"],
                description="Certified public result fixture.",
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
                effect_class="mutating",
                schema_public=True,
                certified_tcb_component="tool-schema-catalog",
                agentic_result_data_class="public",
            ),
            lambda _arguments, _context: {},
        )
        resolve = build_hosted_tool_result_admission_resolver(
            cli_registry=self.cli,
            mcp_registry=self.mcp,
        )
        preflight = build_hosted_tool_result_preflight_resolver(
            cli_registry=self.cli,
            mcp_registry=self.mcp,
        )

        result = resolve(
            "core-capability:cli.run",
            {"command_id": "core.public-result"},
            {"status": "completed"},
            self.actor,
        )
        preflight_result = preflight(
            "core-capability:cli.run",
            {"command_id": "core.public-result"},
            self.actor,
        )

        self.assertEqual(result.classification.data_class, "public")
        self.assertTrue(preflight_result.admitted_before_effect)
        self.assertEqual(preflight_result.guaranteed_data_class, "public")

    def _assert_digest_matches(self, result: RuntimeToolSurfaceResult) -> None:
        encoded = json.dumps(
            result.payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self.assertEqual(result.classification.source_digest, content_sha256(encoded))


if __name__ == "__main__":
    unittest.main()
