from __future__ import annotations

from datetime import UTC, datetime

from core.cli.command_registry import CliCommandRegistry
from core.cli.models import CliCommandDefinition, CliInvocationPolicy
from core.mcp.models import McpInvocationPolicy, McpToolDefinition
from core.mcp.tool_registry import McpToolRegistry
from core.providers.capability_models import RuntimeCapabilitySet
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.tool_catalog import (
    RuntimeAppInterfaceResolver,
    RuntimeExternalToolSurface,
    RuntimeToolActorContext,
    RuntimeToolCatalogBuilder,
)
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_ledger import RuntimeToolLedger
from core.runtime.tool_orchestrator import RuntimeToolConfirmationPolicy, RuntimeToolOrchestrator
from core.runtime.tool_private_payloads import InMemoryRuntimeToolPrivatePayloadStore
from core.runtime.tool_schema import provider_tool_name
from tests.support.collections import FakeCollection


NOW = datetime(2026, 8, 16, tzinfo=UTC)

OBJECT_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}


class _FakeAppResolver(RuntimeAppInterfaceResolver):
    def __init__(self) -> None:
        self.calls = 0

    def list_tool_surfaces(self, *, context):
        return [
            RuntimeExternalToolSurface(
                handle="app-interface:documents:v1:lookup",
                description="Look up a document through the selected provider.",
                input_schema=OBJECT_SCHEMA,
                output_schema=OBJECT_SCHEMA,
                effect_class="read",
                safe_to_retry=True,
            )
        ]

    def invoke_tool_surface(self, *, handle, arguments, context, idempotency_key):
        self.calls += 1
        return {"value": arguments["value"]}


class _FailOncePrivatePayloadStore(InMemoryRuntimeToolPrivatePayloadStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_put = True

    def put(
        self,
        *,
        workspace_id: str,
        session_id: str,
        payload: bytes,
        private_ref: str | None = None,
    ) -> str:
        if self.fail_next_put:
            self.fail_next_put = False
            raise RuntimeToolError("synthetic_private_store_crash")
        return super().put(
            workspace_id=workspace_id,
            session_id=session_id,
            payload=payload,
            private_ref=private_ref,
        )


class _RuntimeToolOrchestratorFixture:
    def setUp(self) -> None:
        self.cli_calls = 0
        self.mcp_calls = 0
        self.cli_registry = CliCommandRegistry()
        self.mcp_registry = McpToolRegistry()
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
        self.mcp_registry.register_tool(
            McpToolDefinition(
                tool_name="fixture_mutate",
                description="Mutate a fixture.",
                input_schema=OBJECT_SCHEMA,
                output_schema=OBJECT_SCHEMA,
                owner_kind="core",
                owner_id="test",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(False, True, True, False),
                entrypoint_path=None,
                effect_class="mutating",
                supports_idempotency=True,
            ),
            self._mutate,
        )
        self.tool_invocations = FakeCollection()
        self.tool_grants = FakeCollection()
        self.store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                tool_invocations=self.tool_invocations,
                tool_confirmation_grants=self.tool_grants,
            )
        )
        self.private_store = InMemoryRuntimeToolPrivatePayloadStore()
        self.ledger = RuntimeToolLedger(
            store=self.store,
            private_payload_store=self.private_store,
            digest_key=b"runtime-tool-test-key-32-bytes!!",
        )
        self.app_resolver = _FakeAppResolver()
        self.orchestrator = self._orchestrator()
        self.authority = self._authority(
            "cli:fixture.read",
            "mcp:fixture_mutate",
            "app-interface:documents:v1:lookup",
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
        self.policy = RuntimeToolConfirmationPolicy(
            policy_revision="policy:1",
            require_confirmation_for_mutating=True,
            require_confirmation_for_destructive=True,
            max_tool_result_bytes=1024,
        )

    def _orchestrator(self) -> RuntimeToolOrchestrator:
        return RuntimeToolOrchestrator(
            catalog_builder=RuntimeToolCatalogBuilder(
                cli_registry=self.cli_registry,
                mcp_registry=self.mcp_registry,
                app_interface_resolver=self.app_resolver,
            ),
            ledger=self.ledger,
        )

    def _authority(self, *handles: str) -> EffectiveRuntimeAuthority:
        return EffectiveRuntimeAuthority(
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
            allowed_tool_handles=handles,
            execution_mode="sandbox",
            egress_policy_id="fake-data",
            policy_revision_set=("policy:1",),
            health_revision="health:1",
            authority_digest="authority-digest",
            computed_at=NOW,
        )

    def _read(self, arguments, context):
        self.cli_calls += 1
        self.assertIsNone(context.idempotency_key)
        return {"value": arguments["value"]}

    def _mutate(self, arguments, context):
        self.mcp_calls += 1
        self.assertTrue(context.idempotency_key)
        return {"value": arguments["value"] + 1}

    def _propose_mutation(self, call_id: str):
        return self.orchestrator.invoke_provider_tool(
            provider_tool_name=provider_tool_name("mcp:fixture_mutate"),
            provider_tool_call_id=call_id,
            arguments={"value": 1},
            authority=self.authority,
            context=self.context,
            turn_id="turn-tools",
            policy=self.policy,
        )
