from __future__ import annotations

from dataclasses import asdict, replace
from types import SimpleNamespace
import unittest

from core.providers.agentic_adapter import RuntimeTurnContext
from core.providers.errors import AgenticRuntimeError
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.provider_input_context import runtime_provider_input_sources
from core.runtime.research_runtime import (
    RESEARCH_HOSTED_WEB_RUNTIME,
    RESEARCH_NATIVE_WEB_RUNTIME,
    RESEARCH_WEB_TOOL_HANDLES,
    assert_research_runtime_input_allowed,
    isolate_research_authority,
    research_provider_catalog,
    research_runtime_policy,
    validate_research_authority,
)
from core.runtime.runtime_session import runtime_session_from_document
from core.runtime.semantic_envelope import HostedSemanticEnvelopeCompiler
from core.runtime.tool_catalog import (
    RuntimeToolCatalog,
    RuntimeToolDescriptor,
)
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class ResearchRuntimeTest(unittest.TestCase):
    @staticmethod
    def research_catalog() -> RuntimeToolCatalog:
        descriptors = []
        for index, handle in enumerate(RESEARCH_WEB_TOOL_HANDLES):
            field = "query" if handle.endswith("web_search") else "url"
            schema = {
                "type": "object",
                "properties": {
                    field: {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500 if field == "query" else 4096,
                    }
                },
                "required": [field],
                "additionalProperties": False,
            }
            descriptors.append(
                RuntimeToolDescriptor(
                    provider_name=f"research_tool_{index}",
                    handle=handle,
                    surface_kind="mcp",
                    source_id=handle.removeprefix("mcp:"),
                    description="Read the public web.",
                    input_schema=schema,
                    original_input_schema=schema,
                    output_schema=None,
                    effect_class="read",
                    supports_idempotency=False,
                    safe_to_retry=True,
                    schema_owner_kind="app",
                    schema_data_class="public",
                    schema_trust_level="trusted_platform",
                    reviewed_schema_component="tool-schema-catalog",
                )
            )
        return RuntimeToolCatalog(
            tuple(descriptors)
        )

    def test_policy_and_live_authority_are_narrowed_to_web_reads(self) -> None:
        harness = HostedAgenticHarness(self)
        policy = research_runtime_policy(harness.policy)

        self.assertEqual(policy.allowed_surface_kinds, ("mcp",))
        self.assertEqual(policy.tool_handle_mode, "exact")
        self.assertEqual(policy.allowed_tool_handles, RESEARCH_WEB_TOOL_HANDLES)
        self.assertFalse(policy.allow_filesystem_list)
        self.assertFalse(policy.allow_filesystem_read)
        self.assertFalse(policy.allow_filesystem_write)
        self.assertFalse(policy.allow_shell)

        authority = isolate_research_authority(
            replace(
                harness.authority,
                allowed_tool_handles=(
                    "cli:fixture.read",
                    *RESEARCH_WEB_TOOL_HANDLES,
                ),
                allowed_capabilities=replace(
                    harness.authority.allowed_capabilities,
                    cli=True,
                    mcp=True,
                    tool_orchestration=True,
                    filesystem_read=True,
                    filesystem_write=True,
                    shell=True,
                    app_references=True,
                ),
            ),
            runtime_kind=RESEARCH_HOSTED_WEB_RUNTIME,
        )
        self.assertEqual(authority.allowed_tool_handles, RESEARCH_WEB_TOOL_HANDLES)
        self.assertTrue(authority.allowed_capabilities.mcp)
        self.assertFalse(authority.allowed_capabilities.cli)
        self.assertFalse(authority.allowed_capabilities.filesystem_read)
        self.assertFalse(authority.allowed_capabilities.filesystem_write)
        self.assertFalse(authority.allowed_capabilities.shell)
        self.assertFalse(authority.allowed_capabilities.app_references)
        binding = replace(
            harness.binding,
            runtime_engine_id="maverick-tool-loop",
            execution_family="maverick_agent",
        )
        validate_research_authority(
            binding,
            authority,
            adapter=SimpleNamespace(
                runtime_engine_id=binding.runtime_engine_id,
                adapter_id=binding.adapter_id,
                research_runtime_kind=RESEARCH_HOSTED_WEB_RUNTIME,
            ),
        )

    def test_native_research_authority_has_no_maverick_tools_or_context(self) -> None:
        harness = HostedAgenticHarness(self)
        binding = replace(
            harness.binding,
            runtime_engine_id="codex",
            adapter_id="codex-app-server",
            model_provider_id="codex",
            provider_protocol="codex-app-server-stdio",
            execution_family="native_agent",
        )
        authority = isolate_research_authority(
            harness.authority,
            runtime_kind=RESEARCH_NATIVE_WEB_RUNTIME,
        )
        adapter = SimpleNamespace(
            runtime_engine_id="codex",
            adapter_id="codex-app-server",
            research_runtime_kind=RESEARCH_NATIVE_WEB_RUNTIME,
            research_runtime_available=lambda _binding: True,
        )

        self.assertEqual(authority.allowed_tool_handles, ())
        self.assertFalse(authority.allowed_capabilities.tool_orchestration)
        self.assertFalse(authority.allowed_capabilities.mcp)
        self.assertFalse(authority.allowed_capabilities.cli)
        self.assertFalse(authority.allowed_capabilities.filesystem_read)
        self.assertFalse(authority.allowed_capabilities.filesystem_write)
        self.assertFalse(authority.allowed_capabilities.shell)
        validate_research_authority(binding, authority, adapter=adapter)

        adapter.research_runtime_available = lambda _binding: False
        with self.assertRaisesRegex(
            AgenticRuntimeError,
            "research_runtime_unavailable",
        ):
            validate_research_authority(binding, authority, adapter=adapter)

        adapter.research_runtime_available = lambda _binding: True
        adapter.research_runtime_kind = ""
        with self.assertRaisesRegex(
            AgenticRuntimeError,
            "research_runtime_unavailable",
        ):
            validate_research_authority(binding, authority, adapter=adapter)

    def test_provider_catalog_uses_only_neutral_web_tool_names(self) -> None:
        session = SimpleNamespace(runtime_profile="research")
        catalog = research_provider_catalog(session, self.research_catalog())
        self.assertEqual(
            tuple(item.provider_name for item in catalog.descriptors),
            ("web_search", "web_open"),
        )
        self.assertTrue(
            all(item.schema_owner_kind == "core" for item in catalog.descriptors)
        )
        self.assertTrue(
            all(
                item.reviewed_schema_component == "tool-schema-catalog"
                for item in catalog.descriptors
            )
        )

    def test_provider_catalog_rejects_drifted_browser_schema(self) -> None:
        session = SimpleNamespace(runtime_profile="research")
        catalog = self.research_catalog()
        drifted = replace(
            catalog,
            descriptors=(
                replace(catalog.descriptors[0], original_input_schema={"type": "object"}),
                catalog.descriptors[1],
            ),
        )

        projected = research_provider_catalog(session, drifted)

        self.assertEqual(
            tuple(item.provider_name for item in projected.descriptors),
            ("web_open",),
        )

    def test_runtime_profile_round_trips_and_legacy_records_default_to_workspace(self) -> None:
        harness = HostedAgenticHarness(self)
        document = asdict(harness.session)
        document["runtime_profile"] = "research"
        self.assertEqual(
            runtime_session_from_document(document).runtime_profile,
            "research",
        )
        document.pop("runtime_profile")
        self.assertEqual(
            runtime_session_from_document(document).runtime_profile,
            "workspace",
        )

    def test_semantic_envelope_contains_no_maverick_or_workspace_context(self) -> None:
        harness = HostedAgenticHarness(self)
        session = replace(
            harness.session,
            runtime_profile="research",
            workspace_root="/path/that/does/not/exist",
            system_prompt="hidden agent persona",
            skill_ids=["hidden-skill"],
            skill_catalog_app_id="agents",
        )
        sources = runtime_provider_input_sources(
            harness,
            session=session,
            turn_id="turn-hosted",
            input_text="Find primary sources about the topic.",
            app_references=None,
            attachments=None,
        )
        context = RuntimeTurnContext(
            session=session,
            binding=harness.binding,
            provider_state=harness.provider_state,
            input_text="Find primary sources about the topic.",
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
            input_sources=sources,
        )

        envelope = HostedSemanticEnvelopeCompiler(
            classifier=harness.classify,
            platform_instruction="hidden Maverick platform instruction",
        ).compile(
            context=context,
            input_text=context.input_text,
            catalog=self.research_catalog(),
            tool_results=(),
            provider_private_state=None,
            request_phase="exploration",
        )

        content_blocks = tuple(
            block for block in envelope.blocks if block.kind == "content"
        )
        self.assertEqual(
            tuple(block.provenance for block in content_blocks),
            ("user_input",),
        )
        self.assertEqual(content_blocks[0].content, context.input_text)
        self.assertEqual(
            sum(block.kind == "tool_schema" for block in envelope.blocks),
            2,
        )

    def test_missing_research_web_tool_fails_before_provider_dispatch(self) -> None:
        harness = HostedAgenticHarness(self)
        context = RuntimeTurnContext(
            session=replace(harness.session, runtime_profile="research"),
            binding=harness.binding,
            provider_state=harness.provider_state,
            input_text="Research this.",
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )

        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "research_runtime_unavailable",
        ):
            HostedSemanticEnvelopeCompiler(
                classifier=harness.classify,
                platform_instruction="hidden",
            ).compile(
                context=context,
                input_text=context.input_text,
                catalog=RuntimeToolCatalog(()),
                tool_results=(),
                provider_private_state=None,
                request_phase="exploration",
            )

    def test_workspace_context_is_rejected_at_the_turn_boundary(self) -> None:
        session = type(
            "ResearchSession",
            (),
            {
                "runtime_profile": "research",
                "system_prompt": None,
                "skill_ids": [],
                "skill_catalog_app_id": None,
            },
        )()

        assert_research_runtime_input_allowed(session)
        with self.assertRaisesRegex(
            AgenticRuntimeError,
            "research_runtime_blocks_workspace_context",
        ):
            assert_research_runtime_input_allowed(
                session,
                attachments=({"name": "workspace.txt"},),
            )


if __name__ == "__main__":
    unittest.main()
