from __future__ import annotations

from dataclasses import replace
import json
import unittest

from core.providers.agentic_adapter import RuntimeTurnContext
from core.runtime.execution import execute_runtime_turn
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.hosted_agentic_policy import hosted_egress_policy
from core.runtime.provider_input_context import RuntimeProviderInputSource
from core.runtime.tool_catalog import RuntimeToolCatalog
from core.skills.models import SkillDefinition
from tests.support.hosted_agentic_harness import HostedAgenticHarness
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient


class SemanticEnvelopeTest(unittest.TestCase):
    def test_materializes_scoped_instructions_full_skill_and_stable_digests(self) -> None:
        harness = HostedAgenticHarness(self)
        workspace = harness.root / "workspaces" / "default"
        nested = workspace / "projects" / "alpha"
        nested.mkdir(parents=True)
        (workspace / "AGENTS.md").write_text("Root instruction.\n", encoding="utf-8")
        (workspace / "projects" / "AGENTS.md").write_text(
            "Projects instruction.\n",
            encoding="utf-8",
        )
        skill_root = workspace / "data" / "skills" / "skills" / "complete-skill"
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text(
            "# Complete skill\n\nFollow every materialized step.\n",
            encoding="utf-8",
        )
        session = replace(
            harness.session,
            workdir=str(nested),
            system_prompt="Agent-specific instruction.",
        )
        authority = replace(
            harness.authority,
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                skill_catalog=True,
            ),
        )
        context = RuntimeTurnContext(
            session=session,
            binding=harness.binding,
            provider_state=harness.store.get_provider_state("session-hosted"),
            input_text="Inspect the fixture.",
            correlation_id="turn-hosted",
            effective_authority=authority,
            invoked_skills=(
                SkillDefinition(
                    skill_id="complete-skill",
                    local_skill_id="complete-skill",
                    name="Complete skill",
                    description="Synthetic procedure.",
                    source_root=str(skill_root),
                    owner_kind="workspace",
                    owner_id="default",
                    workspace_id="default",
                    status="available",
                ),
            ),
        )

        first = self._request(harness, context)
        second = self._request(harness, context)

        self.assertEqual(
            first.semantic_source_snapshot_digest,
            second.semantic_source_snapshot_digest,
        )
        self.assertEqual(
            first.provider_egress_projection_digest,
            second.provider_egress_projection_digest,
        )
        self.assertEqual(first.semantic_envelope_schema_version, "1")
        self.assertEqual(first.semantic_projection_compiler_revision, "1")
        provenance = [block.provenance for block in first.content_blocks]
        self.assertEqual(
            provenance,
            [
                "platform_instruction",
                "runtime_context",
                "runtime_capabilities",
                "workspace_instruction",
                "workspace_instruction",
                "agent_instruction",
                "user_input",
                "skill_fragment",
            ],
        )
        instructions = [
            json.loads(block.content)
            for block in first.content_blocks
            if block.provenance == "workspace_instruction"
        ]
        self.assertEqual([item["scope"] for item in instructions], [".", "projects"])
        skill = json.loads(
            next(
                block.content
                for block in first.content_blocks
                if block.provenance == "skill_fragment"
            )
        )
        self.assertIn("every materialized step", skill["instructions"])
        self.assertEqual(
            tuple(metadata.semantic_block_id for metadata in first.source_metadata),
            tuple(
                f"semantic:turn-hosted:{index}"
                for index in range(len(first.source_metadata))
            ),
        )

        (workspace / "projects" / "AGENTS.md").write_text(
            "Changed projects instruction.\n",
            encoding="utf-8",
        )
        changed = self._request(harness, context)
        self.assertNotEqual(
            first.semantic_source_snapshot_digest,
            changed.semantic_source_snapshot_digest,
        )

    def test_unknown_mandatory_source_fails_before_any_egress_decision(self) -> None:
        harness = HostedAgenticHarness(self)
        context = RuntimeTurnContext(
            session=harness.session,
            binding=harness.binding,
            provider_state=harness.store.get_provider_state("session-hosted"),
            input_text="fixture",
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
            input_sources=(
                RuntimeProviderInputSource(
                    "unknown",
                    "silently_dropped_context",
                    "text/plain",
                    "must not disappear",
                ),
            ),
        )
        before = harness.store.list_egress_decisions(session_id="session-hosted")

        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "semantic_block_not_projectable",
        ):
            self._request(harness, context)

        self.assertEqual(
            harness.store.list_egress_decisions(session_id="session-hosted"),
            before,
        )

    def test_persists_source_and_projection_evidence_in_provider_journal(self) -> None:
        harness = HostedAgenticHarness(self)
        client = DeterministicFakeAgenticClient()

        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use the semantic fixture.",
            agentic_adapter=harness.adapter(client),
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(len(client.requests), 1)
        journal = harness.store.list_provider_step_journals(
            session_id="session-hosted"
        )[0]
        request = client.requests[0]
        self.assertEqual(
            journal.semantic_source_snapshot_digest,
            request.semantic_source_snapshot_digest,
        )
        self.assertEqual(
            journal.provider_egress_projection_digest,
            request.provider_egress_projection_digest,
        )
        self.assertEqual(
            journal.semantic_projection_compiler_id,
            request.semantic_projection_compiler_id,
        )
        self.assertEqual(journal.schema_version, "4")

    @staticmethod
    def _request(harness: HostedAgenticHarness, context: RuntimeTurnContext):
        return harness.request_builder.build(
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


if __name__ == "__main__":
    unittest.main()
