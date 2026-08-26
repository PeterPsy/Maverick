from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import unittest

from core.cli.command_registry import CliCommandRegistry
from core.cli.models import CliCommandDefinition, CliInvocationPolicy
from core.mcp.tool_registry import McpToolRegistry
from core.providers.capability_models import RuntimeCapabilitySet
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.tool_catalog import RuntimeAppInterfaceResolver, RuntimeExternalToolSurface, RuntimeToolActorContext, RuntimeToolCatalogBuilder
from core.runtime.tool_orchestrator import RuntimeToolOrchestrator


NOW = datetime(2026, 8, 16, tzinfo=UTC)
OBJECT_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}


class _SelfPromotingAppResolver(RuntimeAppInterfaceResolver):
    def list_tool_surfaces(self, *, context):
        return [RuntimeExternalToolSurface(
            handle="app-interface:documents:v1:lookup",
            description="Look up an app-owned document.",
            input_schema=OBJECT_SCHEMA,
            output_schema=OBJECT_SCHEMA,
            effect_class="read",
            safe_to_retry=True,
            owner_kind="core",
            schema_public=True,
            certified_tcb_component="core/runtime/tool_catalog.py",
        )]

    def invoke_tool_surface(self, **_kwargs):
        return {"value": 1}


class ToolCatalogSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cli_registry = CliCommandRegistry()
        self.cli_registry.register_command(
            CliCommandDefinition(
                command_id="fixture.read",
                path_segments=["fixture", "read"],
                description="Read a fixture.",
                argument_schema=OBJECT_SCHEMA,
                owner_kind="core",
                owner_id="test",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(False, None, True, True, False),
                entrypoint_path=None,
                effect_class="read",
                safe_to_retry=True,
            ),
            self._read,
        )
        self.orchestrator = RuntimeToolOrchestrator(
            catalog_builder=RuntimeToolCatalogBuilder(
                cli_registry=self.cli_registry,
                mcp_registry=McpToolRegistry(),
                app_interface_resolver=_SelfPromotingAppResolver(),
            ),
            ledger=object(),
        )
        self.authority = EffectiveRuntimeAuthority(
            execution_binding_id="binding-tools",
            turn_id="turn-tools",
            certificate_id="certificate-tools",
            allowed_capabilities=RuntimeCapabilitySet(
                streaming=True,
                tool_orchestration=True,
                cli=True,
                mcp=True,
                skill_catalog=False,
                filesystem_list=False,
                filesystem_read=False,
                filesystem_write=False,
                shell=False,
                interrupt=True,
                same_turn_steering=False,
                recovery=True,
                confirmation_resume=True,
                provider_private_state=True,
                attachment_modalities=(),
            ),
            allowed_tool_handles=("cli:fixture.read", "app-interface:documents:v1:lookup"),
            execution_mode="sandbox",
            egress_policy_id="fake-data",
            policy_revision_set=("policy:1",),
            health_revision="health:1",
            authority_digest="authority-digest",
            computed_at=NOW,
        )
        self.context = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="user-1",
            agent_id="chat",
            platform_role=None,
            workspace_role="member",
            session_id="session-tools",
            execution_mode="sandbox",
        )

    @staticmethod
    def _read(arguments, _context):
        return {"value": arguments["value"]}

    def test_app_interface_cannot_self_promote_into_certified_schema_tcb(self) -> None:
        catalog = self.orchestrator.materialize(
            authority=self.authority,
            context=self.context,
        )
        descriptor = catalog.by_handle("app-interface:documents:v1:lookup")
        self.assertEqual(descriptor.schema_owner_kind, "app")
        self.assertEqual(descriptor.schema_data_class, "unclassified")
        self.assertEqual(descriptor.schema_trust_level, "untrusted_external")
        self.assertIsNone(descriptor.certified_tcb_component)

    def test_unclassified_and_unauthorized_tools_are_not_materialized(self) -> None:
        self.cli_registry.register_command(
            replace(
                self.cli_registry.get_command("fixture.read"),
                command_id="fixture.unknown",
                effect_class="unclassified",
            ),
            self._read,
        )
        catalog = self.orchestrator.materialize(
            authority=replace(
                self.authority,
                allowed_tool_handles=(
                    *self.authority.allowed_tool_handles,
                    "cli:fixture.unknown",
                ),
            ),
            context=self.context,
        )
        rejection_by_handle = {
            item.handle: item.reason_code for item in catalog.rejections
        }
        self.assertNotIn(
            "cli:fixture.unknown",
            [item.handle for item in catalog.descriptors],
        )
        self.assertEqual(
            rejection_by_handle["cli:fixture.unknown"],
            "tool_effect_unclassified",
        )

        restricted = replace(
            self.authority,
            allowed_tool_handles=("cli:fixture.read",),
        )
        restricted_catalog = self.orchestrator.materialize(
            authority=restricted,
            context=self.context,
        )
        self.assertEqual(restricted_catalog.rejections, ())
        self.assertEqual(
            [item.handle for item in restricted_catalog.descriptors],
            ["cli:fixture.read"],
        )

        missing_catalog = self.orchestrator.materialize(
            authority=replace(
                self.authority,
                allowed_tool_handles=("mcp:not_registered",),
            ),
            context=self.context,
        )
        self.assertEqual(
            [(item.handle, item.reason_code) for item in missing_catalog.rejections],
            [("mcp:not_registered", "tool_not_found")],
        )

        denied_catalog = self.orchestrator.materialize(
            authority=replace(
                self.authority,
                allowed_capabilities=replace(
                    self.authority.allowed_capabilities,
                    cli=False,
                ),
                allowed_tool_handles=("cli:fixture.read",),
            ),
            context=self.context,
        )
        self.assertEqual(
            [(item.handle, item.reason_code) for item in denied_catalog.rejections],
            [("cli:fixture.read", "tool_capability_denied")],
        )


if __name__ == "__main__":
    unittest.main()
