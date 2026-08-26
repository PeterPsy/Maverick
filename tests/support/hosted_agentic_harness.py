"""Reusable complete hosted-loop fixture for runtime certification tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import os
from unittest.mock import patch

from core.cli.command_registry import CliCommandRegistry
from core.cli.models import CliCommandDefinition, CliInvocationPolicy
from core.egress.agentic_policy import AgenticEgressEvaluator
from core.mcp.models import McpInvocationPolicy, McpToolDefinition
from core.mcp.tool_registry import McpToolRegistry
from core.observability.store import ObservabilityCollections, ObservabilityDocumentStore
from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.providers.agentic_protocol import EphemeralCredential
from core.providers.capability_models import RuntimeCapabilitySet
from core.providers.service import builtin_provider_registry
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW,
    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
    MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW,
)
from core.runtime.execution_binding import build_runtime_execution_binding, canonical_digest
from core.runtime.hosted_agentic_engine import (
    HostedAgenticEngineAdapter,
    build_hosted_turn_status_callback,
)
from core.runtime.hosted_agentic_loop import HostedAgenticLoop
from core.runtime.hosted_agentic_models import (
    HostedContentClassification,
    HostedProviderPrivateCodec,
)
from core.runtime.hosted_agentic_request import HostedAgenticRequestBuilder
from core.runtime.hosted_provider_runtime import (
    HostedProviderRuntime,
    HostedProviderRuntimeRegistry,
)
from core.runtime.private_payload_store import EncryptedRuntimePrivatePayloadStore
from core.runtime.provider_private_state import ProviderPrivateStateService
from core.runtime.provider_state import RuntimeProviderState
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.session_provider_state import initial_runtime_state
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.tool_catalog import RuntimeToolActorContext, RuntimeToolCatalogBuilder
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_ledger import RuntimeToolLedger
from core.runtime.tool_orchestrator import RuntimeToolOrchestrator
from core.runtime.tool_private_payloads import EncryptedRuntimeToolPrivatePayloadStore
from core.runtime.tool_schema import provider_tool_name
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 8, 16, tzinfo=UTC)
OBJECT_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}


class HostedAgenticHarness:
    def __init__(
        self,
        test_case,
        *,
        max_tool_calls: int = 4,
        model_provider_id: str = "fake-model-provider",
        model_id: str = "fake-model-v1",
        provider_protocol: str = "fake-agentic-v1",
        provider_api_version: str | None = "v1",
        routing_constraint=None,
        filesystem_list: bool = False,
    ) -> None:
        feature_flags = patch.dict(
            os.environ,
            {
                MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME: "1",
                MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW: "1",
                MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW: "1",
            },
            clear=False,
        )
        feature_flags.start()
        test_case.addCleanup(feature_flags.stop)
        dispatch_guard = patch(
            "core.runtime.hosted_provider_runtime.require_remote_agentic_dispatch",
            return_value=None,
        )
        dispatch_guard.start()
        test_case.addCleanup(dispatch_guard.stop)
        self.root = make_temp_repo_root(test_case)
        self.filesystem_list = filesystem_list
        self.filesystem_marker = "hosted-loop-filesystem-marker.txt"
        if filesystem_list:
            workspace_root = self.root / "workspaces" / "default"
            workspace_root.mkdir(parents=True, exist_ok=True)
            (workspace_root / self.filesystem_marker).write_text(
                "synthetic hosted-loop marker",
                encoding="utf-8",
            )
        self.cli_calls = 0
        self.mcp_calls = 0
        self.read_result: dict[str, object] | None = None
        self.turn_statuses: list[tuple[str, str]] = []
        self.audit = FakeCollection()
        self.store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                provider_states=FakeCollection(),
                tool_invocations=FakeCollection(),
                tool_confirmation_grants=FakeCollection(),
                egress_decisions=FakeCollection(),
            )
        )
        self.policy = replace(
            codex_runtime_policy(),
            max_steps_per_turn=4,
            max_tool_calls_per_turn=max_tool_calls,
            max_wall_time_seconds=5,
            max_tool_result_bytes=4096,
            max_total_tool_result_bytes=8192,
            max_input_tokens=4096,
            max_output_tokens=1024,
            allowed_surface_kinds=(
                ("core-capability",) if filesystem_list else ("cli", "mcp")
            ),
            tool_handle_mode="exact",
            allowed_tool_handles=(
                ("core-capability:filesystem.list",)
                if filesystem_list
                else ("cli:fixture.read", "mcp:fixture_mutate")
            ),
            allow_filesystem_list=filesystem_list,
            require_confirmation_for_mutating=True,
            require_confirmation_for_destructive=True,
            allowed_remote_data_classes=("public",),
        )
        self.binding = build_runtime_execution_binding(
            session_id="session-hosted",
            workspace_id="default",
            profile_definition_id="profile-hosted",
            profile_definition_revision="1",
            workspace_binding_id="binding-hosted",
            workspace_binding_revision=0,
            capability_certificate_id="certificate-hosted",
            certificate_evidence_digest="a" * 64,
            runtime_engine_id="hosted-agentic",
            adapter_id="hosted-agentic-test-adapter",
            adapter_version="1",
            adapter_artifact_digest="b" * 64,
            model_provider_id=model_provider_id,
            model_id=model_id,
            provider_protocol=provider_protocol,
            provider_api_version=provider_api_version,
            routing_constraint=routing_constraint or codex_routing_constraint(),
            credential_binding_id=None,
            reasoning_effort=None,
            certified_reasoning_efforts=(),
            default_reasoning_effort=None,
            execution_mode="full-access",
            profile_policy_ceiling=self.policy,
            workspace_policy_ceiling=self.policy,
            egress_policy_id="fixture-public-remote",
            egress_policy_revision="1",
            created_at=NOW,
        )
        self.session = RuntimeSessionRecord(
            session_id="session-hosted",
            workspace_id="default",
            agent_id="chat",
            status="running",
            requested_mode="full-access",
            effective_mode="full-access",
            workspace_root=str(self.root / "workspaces" / "default"),
            workdir=str(self.root / "workspaces" / "default"),
            runtime_root=str(self.root / "workspaces" / "default" / "runtime"),
            started_at=NOW,
            updated_at=NOW,
            ended_at=None,
            last_progress_at=NOW,
            owner_user_id="user-1",
            execution_binding=self.binding,
        )
        self.store.insert_session(self.session)
        self.store.save_state(
            initial_runtime_state(
                session_id=self.session.session_id,
                workspace_id=self.session.workspace_id,
                now=NOW,
            )
        )
        self.store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-hosted",
                session_id=self.session.session_id,
                workspace_id=self.session.workspace_id,
                status="active",
                input_text="Use only synthetic fixture data.",
                created_at=NOW,
                updated_at=NOW,
                started_at=NOW,
                completed_at=None,
                failure_reason=None,
            )
        )
        self.provider_state = self.store.initialize_provider_state(
            RuntimeProviderState(
                session_id=self.session.session_id,
                workspace_id=self.session.workspace_id,
                runtime_engine_id=self.binding.runtime_engine_id,
                model_provider_id=self.binding.model_provider_id,
                continuation_id=None,
                provider_thread_id=None,
                provider_request_id=None,
                provider_private_envelope=None,
                revision=0,
                turn_generation=None,
                updated_at=NOW,
            )
        )
        self.authority = self._authority()
        private_store = EncryptedRuntimePrivatePayloadStore(
            repository_root=self.root,
            key_loader=lambda: bytes(range(32)),
        )
        self.orchestrator = self._orchestrator(
            EncryptedRuntimeToolPrivatePayloadStore(private_store)
        )
        self.private_state_service = ProviderPrivateStateService(
            store=self.store,
            payload_store=private_store,
        )
        observability = ObservabilityDocumentStore(
            ObservabilityCollections(
                events=FakeCollection(),
                audit=self.audit,
                metrics=FakeCollection(),
            )
        )
        self.request_builder = HostedAgenticRequestBuilder(
            egress_evaluator=AgenticEgressEvaluator(
                digest_key=b"hosted-agentic-egress-test-key-value",
                observability_store=observability,
                decision_store=self.store,
            ),
            classifier=self.classify,
        )
        provider = builtin_provider_registry().get_provider_definition("codex")
        self.provider = replace(
            provider,
            provider_id="hosted-agentic",
            label="Hosted agentic test",
            default_model_family="fake-model-v1",
        )

    def adapter(
        self,
        client,
        *,
        private_codec: HostedProviderPrivateCodec | None = None,
        credential: EphemeralCredential | None = None,
        cost_estimator=None,
        authority_refresher=None,
    ) -> HostedAgenticEngineAdapter:
        runtimes = HostedProviderRuntimeRegistry()
        runtimes.register(
            HostedProviderRuntime(
                model_provider_id=self.binding.model_provider_id,
                provider_protocol=self.binding.provider_protocol,
                provider_api_version=self.binding.provider_api_version,
                client=client,
                private_codec=private_codec
                or HostedProviderPrivateCodec(
                    codec_id="fake-hosted-codec",
                    codec_version="1",
                    schema_version="1",
                    content_type="application/vnd.maverick.fake-private",
                ),
                cost_estimator=cost_estimator or (lambda _request: 0),
            )
        )
        loop = HostedAgenticLoop(
            provider_runtimes=runtimes,
            request_builder=self.request_builder,
            tool_orchestrator_resolver=lambda _context, _actor: self.orchestrator,
            tool_ledger=self.orchestrator.ledger,
            private_state_service=self.private_state_service,
            policy_resolver=lambda _context: self.policy,
            authority_refresher=authority_refresher or (lambda _context: self.authority),
            actor_context_resolver=lambda _context: RuntimeToolActorContext(
                workspace_id="default",
                actor_id="user-1",
                agent_id="chat",
                platform_role=None,
                workspace_role="member",
                session_id="session-hosted",
                execution_mode="full-access",
            ),
            credential_resolver=lambda _context: credential,
            turn_status_callback=self._turn_status_callback(),
            confirmation_poll_seconds=0.01,
        )
        return HostedAgenticEngineAdapter(
            runtime_engine_id=self.binding.runtime_engine_id,
            adapter_id=self.binding.adapter_id,
            adapter_version=self.binding.adapter_version,
            loop=loop,
        )

    @staticmethod
    def classify(_context, provenance: str, _content: object) -> HostedContentClassification:
        trust = {
            "platform_instruction": "trusted_platform",
            "tool_schema": "trusted_platform",
            "provider_state": "trusted_platform",
            "tool_result": "untrusted_tool_output",
        }.get(provenance, "trusted_actor")
        return HostedContentClassification("public", trust)

    def _authority(self) -> EffectiveRuntimeAuthority:
        authority = EffectiveRuntimeAuthority(
            execution_binding_id=self.binding.execution_binding_id,
            turn_id="turn-hosted",
            certificate_id=self.binding.capability_certificate_id,
            allowed_capabilities=RuntimeCapabilitySet(
                streaming=True,
                tool_orchestration=True,
                cli=not self.filesystem_list,
                mcp=not self.filesystem_list,
                skill_catalog=False,
                filesystem_list=self.filesystem_list,
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
            allowed_tool_handles=(
                ("core-capability:filesystem.list",)
                if self.filesystem_list
                else ("cli:fixture.read", "mcp:fixture_mutate")
            ),
            execution_mode="full-access",
            egress_policy_id=self.binding.egress_policy_id,
            policy_revision_set=("policy:test:1",),
            health_revision="health:test:1",
            authority_digest="",
            computed_at=NOW,
        )
        return replace(authority, authority_digest=canonical_digest(authority))

    def _turn_status_callback(self):
        persist = build_hosted_turn_status_callback(self.store)

        def callback(status: str, invocation_id: str) -> None:
            persist(status, invocation_id)
            self.turn_statuses.append((status, invocation_id))

        return callback

    def _orchestrator(self, private_payload_store) -> RuntimeToolOrchestrator:
        cli = CliCommandRegistry()
        cli.register_command(
            CliCommandDefinition(
                command_id="fixture.read",
                path_segments=["fixture", "read"],
                description="Read one deterministic fixture value.",
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
        mcp = McpToolRegistry()
        mcp.register_tool(
            McpToolDefinition(
                tool_name="fixture_mutate",
                description="Mutate one deterministic fixture value.",
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
        ledger = RuntimeToolLedger(
            store=self.store,
            private_payload_store=private_payload_store,
            digest_key=b"hosted-agentic-tool-ledger-test-key",
        )
        return RuntimeToolOrchestrator(
            catalog_builder=RuntimeToolCatalogBuilder(
                cli_registry=cli,
                mcp_registry=mcp,
                core_capabilities=(
                    build_core_runtime_tool_capabilities(
                        workspace_id="default",
                        workspace_root=self.root / "workspaces" / "default",
                    )
                    if self.filesystem_list
                    else ()
                ),
            ),
            ledger=ledger,
        )

    def _read(self, arguments, _context):
        self.cli_calls += 1
        return self.read_result or {"value": arguments["value"]}

    def _mutate(self, arguments, _context):
        self.mcp_calls += 1
        return {"value": arguments["value"] + 1}

    @property
    def read_tool_name(self) -> str:
        return provider_tool_name("cli:fixture.read")

    @property
    def mutate_tool_name(self) -> str:
        return provider_tool_name("mcp:fixture_mutate")

    @property
    def filesystem_list_tool_name(self) -> str:
        return provider_tool_name("core-capability:filesystem.list")
