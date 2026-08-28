from __future__ import annotations

from dataclasses import replace
import json
import unittest

from core.runtime.hosted_agentic_factory import classify_hosted_content_fail_closed
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.hosted_agentic_policy import hosted_egress_policy
from core.providers.agentic_adapter import RuntimeTurnContext
from core.runtime.execution import execute_runtime_turn
from core.runtime.provider_input_context import RuntimeProviderInputSource
from core.runtime.tool_catalog import (
    RuntimeToolCatalog,
    RuntimeToolDescriptor,
    RuntimeToolRejection,
)
from core.skills.models import SkillDefinition
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class HostedAgenticEgressTest(unittest.TestCase):
    def test_tool_result_host_paths_are_redacted_before_the_next_request(self) -> None:
        harness = HostedAgenticHarness(self)
        harness.read_result = {
            "workspace_file": f"{harness.session.workspace_root}/AGENTS.md",
            "host_reference": (
                "The installation root is `/home/ubuntu/projects/maverick-v3`."
            ),
        }
        client = DeterministicFakeAgenticClient(tool_name=harness.read_tool_name)

        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=harness.adapter(client),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )

        self.assertEqual(result.exit_code, 0)
        exported = json.loads(client.requests[1].tool_results[0].content)
        self.assertEqual(exported["workspace_file"], "workspace://default/AGENTS.md")
        self.assertEqual(
            exported["host_reference"],
            "The installation root is `<redacted-host-path>`.",
        )
        decisions = harness.store.list_egress_decisions(session_id="session-hosted")
        tool_result = next(
            decision for decision in decisions if decision.provenance == "tool_result"
        )
        self.assertEqual(
            tool_result.transformation,
            "workspace_path_reference+host_path_redaction",
        )

    def test_app_owned_dynamic_and_uncertified_tool_schemas_fail_before_dispatch(self) -> None:
        harness = HostedAgenticHarness(self)
        context = RuntimeTurnContext(
            session=harness.session,
            binding=harness.binding,
            provider_state=harness.store.get_provider_state("session-hosted"),
            input_text="synthetic fixture",
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )
        base = dict(
            provider_name="fixture_tool",
            handle="app-interface:fixture:v1:read",
            surface_kind="app-interface",
            source_id="fixture",
            description="Fixture tool.",
            input_schema={"type": "object", "additionalProperties": False},
            original_input_schema={"type": "object", "additionalProperties": False},
            output_schema=None,
            effect_class="read",
            supports_idempotency=False,
            safe_to_retry=True,
        )
        descriptors = (
            RuntimeToolDescriptor(
                **base,
                schema_owner_kind="app",
                schema_data_class="public",
                schema_trust_level="trusted_platform",
                certified_tcb_component="tool-schema-catalog",
            ),
            RuntimeToolDescriptor(
                **{
                    **base,
                    "handle": "cli:dynamic.fixture",
                    "surface_kind": "cli",
                },
                schema_owner_kind="core",
                schema_data_class="unclassified",
                schema_trust_level="trusted_platform",
                certified_tcb_component=None,
            ),
        )

        for descriptor in descriptors:
            with self.subTest(handle=descriptor.handle):
                with self.assertRaisesRegex(
                    HostedAgenticLoopError,
                    "tool_schema_not_certified",
                ):
                    harness.request_builder.build(
                        context=context,
                        step=0,
                        input_text="synthetic fixture",
                        catalog=RuntimeToolCatalog((descriptor,)),
                        tool_results=(),
                        provider_private_state=None,
                        egress_policy=hosted_egress_policy(context, harness.policy),
                        destination_upstream_id=None,
                        max_output_tokens=32,
                    )

    def test_generic_classifier_never_promotes_tool_schema_to_public(self) -> None:
        classification = classify_hosted_content_fail_closed(
            None,
            "tool_schema",
            {"browser": "claimed-public"},
        )

        self.assertEqual(classification.data_class, "unclassified")
        self.assertEqual(classification.trust_level, "trusted_actor")

    def test_prompt_skill_attachment_and_app_reference_keep_distinct_provenance(self) -> None:
        harness = HostedAgenticHarness(self)
        skill_root = (
            harness.root
            / "workspaces"
            / "default"
            / "data"
            / "skills"
            / "skills"
            / "fixture-skill"
        )
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text(
            "# Fixture skill\n\nUse the complete synthetic procedure.\n",
            encoding="utf-8",
        )
        effective_authority = replace(
            harness.authority,
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                skill_catalog=True,
                attachment_modalities=("text",),
                app_references=True,
            ),
        )
        context = RuntimeTurnContext(
            session=harness.session,
            binding=harness.binding,
            provider_state=harness.store.get_provider_state("session-hosted"),
            input_text="legacy-composed-input-must-not-be-used",
            correlation_id="turn-hosted",
            effective_authority=effective_authority,
            input_sources=(
                RuntimeProviderInputSource(
                    "prompt",
                    "prompt",
                    "text/plain",
                    "synthetic fixture",
                ),
                RuntimeProviderInputSource(
                    "attachment",
                    "attachment",
                    "application/json",
                    {"relative_path": "storage/uploaded/fixture.txt"},
                    capability_modality="text/plain",
                ),
                RuntimeProviderInputSource(
                    "app-reference",
                    "app_reference",
                    "application/json",
                    {"app_id": "crm", "entity_id": "fixture"},
                ),
            ),
            invoked_skills=(
                SkillDefinition(
                    skill_id="fixture-skill",
                    local_skill_id="fixture-skill",
                    name="Fixture skill",
                    description="Synthetic only.",
                    source_root=str(skill_root),
                    owner_kind="workspace",
                    owner_id="default",
                    workspace_id="default",
                    status="available",
                ),
            ),
        )

        request = harness.request_builder.build(
            context=context,
            step=0,
            input_text=context.input_text,
            catalog=RuntimeToolCatalog(()),
            tool_results=(),
            provider_private_state=None,
            egress_policy=hosted_egress_policy(context, harness.policy),
            destination_upstream_id=None,
            max_output_tokens=32,
        )

        provenance = tuple(block.provenance for block in request.content_blocks)
        self.assertEqual(
            provenance,
            (
                "platform_instruction",
                "runtime_context",
                "runtime_capabilities",
                "user_input",
                "attachment",
                "app_reference",
                "skill_fragment",
            ),
        )
        self.assertEqual(
            tuple(item.provenance for item in request.source_metadata),
            provenance,
        )
        skill = next(
            block for block in request.content_blocks if block.provenance == "skill_fragment"
        )
        self.assertIn("complete synthetic procedure", skill.content.decode("utf-8"))
        self.assertEqual(len(request.semantic_source_snapshot_digest), 64)
        self.assertEqual(len(request.provider_egress_projection_digest), 64)

    def test_catalog_rejection_blocks_before_egress_instead_of_being_silent(self) -> None:
        harness = HostedAgenticHarness(self)
        context = RuntimeTurnContext(
            session=harness.session,
            binding=harness.binding,
            provider_state=harness.store.get_provider_state("session-hosted"),
            input_text="synthetic fixture",
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )
        decisions_before = harness.store.list_egress_decisions(
            session_id="session-hosted"
        )
        with self.assertRaisesRegex(HostedAgenticLoopError, "tool_not_authorized"):
            harness.request_builder.build(
                context=context,
                step=0,
                input_text=context.input_text,
                catalog=RuntimeToolCatalog(
                    (),
                    (
                        RuntimeToolRejection(
                            "app-interface:uncertified",
                            "app-interface",
                            "tool_not_authorized",
                        ),
                    ),
                ),
                tool_results=(),
                provider_private_state=None,
                egress_policy=hosted_egress_policy(context, harness.policy),
                destination_upstream_id=None,
                max_output_tokens=32,
            )
        self.assertEqual(
            harness.store.list_egress_decisions(session_id="session-hosted"),
            decisions_before,
        )

    def test_refreshed_authority_blocks_context_before_any_egress_decision(self) -> None:
        harness = HostedAgenticHarness(self)
        cases = (
            (
                {"invoked_skills": ("fixture-skill",)},
                "agentic_skill_catalog_not_effective",
            ),
            (
                {
                    "input_sources": (
                        RuntimeProviderInputSource(
                            "attachment",
                            "attachment",
                            "application/json",
                            {"relative_path": "storage/uploaded/fixture.png"},
                            capability_modality="image/png",
                        ),
                    )
                },
                "agentic_attachment_modality_not_certified",
            ),
            (
                {
                    "input_sources": (
                        RuntimeProviderInputSource(
                            "app-reference",
                            "app_reference",
                            "application/json",
                            {"app_id": "crm"},
                        ),
                    )
                },
                "agentic_app_references_not_effective",
            ),
        )
        for context_updates, reason_code in cases:
            context = RuntimeTurnContext(
                session=harness.session,
                binding=harness.binding,
                provider_state=harness.store.get_provider_state("session-hosted"),
                input_text="synthetic fixture",
                correlation_id="turn-hosted",
                effective_authority=harness.authority,
                **context_updates,
            )
            before = harness.store.list_egress_decisions(
                session_id="session-hosted"
            )
            with self.subTest(reason_code=reason_code), self.assertRaisesRegex(
                HostedAgenticLoopError,
                reason_code,
            ):
                harness.request_builder.build(
                    context=context,
                    step=0,
                    input_text=context.input_text,
                    catalog=RuntimeToolCatalog(()),
                    tool_results=(),
                    provider_private_state=None,
                    egress_policy=hosted_egress_policy(context, harness.policy),
                    destination_upstream_id=None,
                    max_output_tokens=32,
                )
            self.assertEqual(
                harness.store.list_egress_decisions(session_id="session-hosted"),
                before,
            )


if __name__ == "__main__":
    unittest.main()
