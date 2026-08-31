from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.egress.classification import validated_classification
from core.providers.agentic_adapter import RuntimeTurnContext
from core.providers.agentic_protocol import (
    AgenticProviderPrivateState,
    AgenticSourceMetadata,
)
from core.runtime.execution import execute_runtime_turn
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedContentClassification,
)
from core.runtime.hosted_agentic_policy import hosted_egress_policy
from core.runtime.provider_input_context import (
    RuntimeProviderInputSource,
    runtime_provider_input_sources,
)
from core.runtime.tool_catalog import RuntimeToolCatalog
from core.skills.models import SkillDefinition
from tests.support.hosted_agentic_harness import HostedAgenticHarness
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient


class SemanticEnvelopeTest(unittest.TestCase):
    def test_transient_inputs_require_exact_server_owned_admission_classification(self) -> None:
        session = SimpleNamespace(
            workspace_id="default",
            session_id="session-input",
            workspace_root="/tmp",
        )
        source = runtime_provider_input_sources(
            SimpleNamespace(
                inter_agent_store=None,
                workspace_store=None,
                runtime_input_classification_resolver=None,
            ),
            session=session,
            turn_id="turn-input",
            input_text="confidential account narrative",
            app_references=None,
            attachments=None,
        )[0]
        self.assertEqual(source.classification.data_class, "unclassified")

        def classify(observation, _content):
            return validated_classification(
                data_class="public",
                provenance=observation.provenance,
                trust_level="trusted_actor",
                source_ref=observation.source_ref,
                source_revision=observation.source_revision,
                source_digest=observation.source_digest,
                resource_identity=observation.resource_identity,
                classification_revision=7,
            )

        admitted = runtime_provider_input_sources(
            SimpleNamespace(
                inter_agent_store=None,
                workspace_store=None,
                runtime_input_classification_resolver=classify,
            ),
            session=session,
            turn_id="turn-input",
            input_text="explicitly classified fixture",
            app_references=None,
            attachments=None,
        )[0]
        self.assertEqual(admitted.classification.data_class, "public")
        self.assertEqual(admitted.classification.classification_revision, 7)

        def mismatched(observation, content):
            return replace(
                classify(observation, content),
                resource_identity="different-source",
            )

        rejected = runtime_provider_input_sources(
            SimpleNamespace(
                inter_agent_store=None,
                workspace_store=None,
                runtime_input_classification_resolver=mismatched,
            ),
            session=session,
            turn_id="turn-input",
            input_text="explicitly classified fixture",
            app_references=None,
            attachments=None,
        )[0]
        self.assertEqual(rejected.classification.data_class, "unclassified")

    def test_attachment_is_an_explicit_authorized_workspace_reference(self) -> None:
        harness = HostedAgenticHarness(self)
        authority = replace(
            harness.authority,
            allowed_tool_handles=(
                *harness.authority.allowed_tool_handles,
                "core-capability:filesystem.read",
            ),
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                filesystem_read=True,
                attachment_modalities=("file",),
            ),
        )
        source = RuntimeProviderInputSource(
            source_id="attachment:0",
            provenance="attachment",
            content_type="application/json",
            content={
                "attachment_id": "attachment-1",
                "name": "evidence.pdf",
                "workspace_relative_path": "attachments/evidence.pdf",
                "media_type": "application/pdf",
                "size_bytes": 128,
                "projection": {
                    "mode": "workspace_reference",
                    "read_capability": "core-capability:filesystem.read",
                    "read_encoding": "base64",
                },
            },
            capability_modality="application/pdf",
            projection_mode="workspace_reference",
        )
        context = RuntimeTurnContext(
            session=harness.session,
            binding=harness.binding,
            provider_state=harness.store.get_provider_state("session-hosted"),
            input_text="Inspect the attachment.",
            correlation_id="turn-hosted",
            effective_authority=authority,
            input_sources=(source,),
        )

        request = self._request(harness, context)

        attachment = next(
            block for block in request.content_blocks if block.provenance == "attachment"
        )
        projection = json.loads(attachment.content)
        self.assertEqual(
            projection["workspace_relative_path"],
            "attachments/evidence.pdf",
        )
        self.assertEqual(
            projection["projection"]["read_capability"],
            "core-capability:filesystem.read",
        )
        self.assertEqual(projection["projection"]["read_encoding"], "base64")
        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "attachment_projection_not_supported",
        ):
            self._request(
                harness,
                replace(
                    context,
                    input_sources=(replace(source, projection_mode=None),),
                ),
            )

    def test_attachment_metadata_is_joined_and_attachment_only_omits_empty_prompt(
        self,
    ) -> None:
        harness = HostedAgenticHarness(self)
        authority = replace(
            harness.authority,
            allowed_tool_handles=(
                *harness.authority.allowed_tool_handles,
                "core-capability:filesystem.read",
            ),
            allowed_capabilities=replace(
                harness.authority.allowed_capabilities,
                filesystem_read=True,
                attachment_modalities=("file",),
            ),
        )

        def classify(observation, content):
            data_class = (
                "credential_or_secret"
                if "secret-name" in json.dumps(content, sort_keys=True)
                else "public"
            )
            return validated_classification(
                data_class=data_class,
                provenance=observation.provenance,
                trust_level="trusted_actor",
                source_ref=observation.source_ref,
                source_revision=observation.source_revision,
                source_digest=observation.source_digest,
                resource_identity=observation.resource_identity,
                classification_revision=3,
            )

        file_classification = validated_classification(
            data_class="public",
            provenance="attachment",
            trust_level="trusted_actor",
            source_ref="attachments/benign.txt",
            source_revision="a" * 64,
            source_digest="a" * 64,
            resource_identity="attachment-file:benign",
            classification_revision=2,
        )
        state = SimpleNamespace(
            inter_agent_store=None,
            workspace_store=None,
            runtime_input_classification_resolver=classify,
        )
        with patch(
            "core.runtime.provider_input_context._attachment_classification",
            return_value=file_classification,
        ):
            benign_sources = runtime_provider_input_sources(
                state,
                session=harness.session,
                turn_id="turn-hosted",
                input_text="",
                app_references=None,
                attachments=[
                    {
                        "id": "attachment-1",
                        "name": "benign.txt",
                        "relativePath": "attachments/benign.txt",
                        "type": "text/plain",
                        "size": 7,
                    }
                ],
            )
            sources = runtime_provider_input_sources(
                state,
                session=harness.session,
                turn_id="turn-hosted",
                input_text="",
                app_references=None,
                attachments=[
                    {
                        "id": "attachment-1",
                        "name": "secret-name=fixture-token",
                        "relativePath": "attachments/benign.txt",
                        "type": "text/plain",
                        "size": 7,
                    }
                ],
            )

        self.assertEqual(len(benign_sources), 1)
        self.assertEqual(benign_sources[0].classification.data_class, "public")
        benign_context = RuntimeTurnContext(
            session=harness.session,
            binding=harness.binding,
            provider_state=harness.store.get_provider_state("session-hosted"),
            input_text="",
            correlation_id="turn-hosted",
            effective_authority=authority,
            input_sources=benign_sources,
        )
        benign_request = self._request(harness, benign_context)
        self.assertEqual(
            sum(
                block.provenance == "attachment"
                for block in benign_request.content_blocks
            ),
            1,
        )
        self.assertFalse(
            any(
                block.provenance == "user_input"
                for block in benign_request.content_blocks
            )
        )

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].provenance, "attachment")
        self.assertEqual(
            sources[0].classification.data_class,
            "credential_or_secret",
        )
        context = RuntimeTurnContext(
            session=harness.session,
            binding=harness.binding,
            provider_state=harness.store.get_provider_state("session-hosted"),
            input_text="",
            correlation_id="turn-hosted",
            effective_authority=authority,
            input_sources=sources,
        )
        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "egress_data_class_denied",
        ):
            self._request(harness, context)

    def test_invalid_attachment_metadata_is_never_silently_dropped(self) -> None:
        for attachment in (
            {"name": "missing-path.pdf"},
            {"name": "escape.pdf", "relativePath": "../escape.pdf"},
            {"name": "numeric-path.pdf", "relativePath": 42},
            {
                "name": "invalid-size.pdf",
                "relativePath": "attachments/invalid-size.pdf",
                "size": True,
            },
        ):
            with self.subTest(attachment=attachment), self.assertRaisesRegex(
                ValueError,
                "agentic_attachment_metadata_invalid",
            ):
                runtime_provider_input_sources(
                    SimpleNamespace(inter_agent_store=None, workspace_store=None),
                    session=SimpleNamespace(
                        workspace_id="default",
                        session_id="session-attachment",
                        workspace_root="/tmp",
                    ),
                    turn_id="turn-attachment",
                    input_text="fixture",
                    app_references=None,
                    attachments=[attachment],
                )

    def test_semantic_block_rejects_a_classification_for_different_bytes(self) -> None:
        harness = HostedAgenticHarness(self)
        mismatched = validated_classification(
            data_class="public",
            provenance="user_input",
            trust_level="trusted_actor",
            source_ref="runtime-turn:turn-hosted:mismatched",
            source_revision="b" * 64,
            source_digest="b" * 64,
            resource_identity="runtime-input:mismatched",
            classification_revision=1,
        )
        context = RuntimeTurnContext(
            session=harness.session,
            binding=harness.binding,
            provider_state=harness.store.get_provider_state("session-hosted"),
            input_text="secret bytes not covered by the classification",
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
            input_sources=(
                RuntimeProviderInputSource(
                    "mismatched",
                    "user_input",
                    "text/plain",
                    "secret bytes not covered by the classification",
                    classification=mismatched,
                ),
            ),
        )
        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "egress_data_class_denied",
        ):
            self._request(harness, context)

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
                    name="secret-name=fixture-token",
                    description="secret-description=fixture-token",
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
        self.assertEqual(first.semantic_projection_compiler_revision, "7")
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
        skill = next(
            block.content.decode("utf-8")
            for block in first.content_blocks
            if block.provenance == "skill_fragment"
        )
        self.assertIn("every materialized step", skill)
        self.assertNotIn("fixture-token", skill)
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

    def test_skill_directory_symlink_fails_before_materialization(self) -> None:
        harness = HostedAgenticHarness(self)
        workspace = harness.root / "workspaces" / "default"
        real = workspace / "data" / "skills" / "skills" / "real-skill"
        real.mkdir(parents=True)
        (real / "SKILL.md").write_text("# Real skill\n", encoding="utf-8")
        alias = real.parent / "alias-skill"
        alias.symlink_to(real, target_is_directory=True)
        context = RuntimeTurnContext(
            session=harness.session,
            binding=harness.binding,
            provider_state=harness.store.get_provider_state("session-hosted"),
            input_text="Use the selected skill.",
            correlation_id="turn-hosted",
            effective_authority=replace(
                harness.authority,
                allowed_capabilities=replace(
                    harness.authority.allowed_capabilities,
                    skill_catalog=True,
                ),
            ),
            invoked_skills=(
                SkillDefinition(
                    skill_id="alias-skill",
                    local_skill_id="alias-skill",
                    name="Alias",
                    description="Alias fixture.",
                    source_root=str(alias),
                    owner_kind="workspace",
                    owner_id="default",
                    workspace_id="default",
                    status="available",
                ),
            ),
        )

        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "skill_materialization_failed",
        ):
            self._request(harness, context)

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

    def test_revoked_transitive_provider_state_fails_before_continuation_egress(
        self,
    ) -> None:
        harness = HostedAgenticHarness(self)
        context = RuntimeTurnContext(
            session=harness.session,
            binding=harness.binding,
            provider_state=harness.store.get_provider_state("session-hosted"),
            input_text="Continue the fixture.",
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )

        def revalidate(_context, classification):
            if classification.classification_authority_bound is not True:
                return classification
            return HostedContentClassification(
                "unclassified",
                "untrusted_external",
                source_ref=classification.source_ref,
                source_revision=classification.source_revision,
                resource_identity=classification.resource_identity,
                classification_revision=None,
                content_digest=classification.content_digest,
                classification_authority_bound=None,
            )

        harness.request_builder.classification_revalidator = revalidate
        harness.request_builder.semantic_compiler.classification_revalidator = (
            revalidate
        )
        stale = AgenticSourceMetadata(
            source_block_digest="1" * 64,
            source_data_class="public",
            source_trust_level="untrusted_tool_output",
            provenance="tool_result",
            source_ref="historical-result",
            source_revision="2" * 64,
            resource_identity="historical-result:1",
            classification_revision=1,
            classification_authority_id="runtime-public-authority-1",
            classification_authority_kind="runtime_public_content_authority",
            classification_authority_ref="hosted-full-workspace",
            classification_authority_revision=1,
            classification_authority_digest="3" * 64,
            classification_authority_policy_revision=(
                "core-hosted-public-workspace-v2"
            ),
            classification_authority_bound=True,
        )
        private_state = AgenticProviderPrivateState(
            codec_id="fake-private-codec",
            codec_version="1",
            schema_version="1",
            content_type="application/octet-stream",
            content=b"private-continuation",
            source_metadata=(stale,),
            effective_data_class="public",
            effective_trust_level="untrusted_tool_output",
            provider_request_id="provider-request-1",
            turn_generation="turn-generation-1",
        )

        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "egress_data_class_denied",
        ):
            harness.request_builder.build(
                context=context,
                step=0,
                input_text=context.input_text,
                catalog=RuntimeToolCatalog(()),
                tool_results=(),
                provider_private_state=private_state,
                egress_policy=hosted_egress_policy(context, harness.policy),
                destination_upstream_id=None,
                max_output_tokens=32,
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
