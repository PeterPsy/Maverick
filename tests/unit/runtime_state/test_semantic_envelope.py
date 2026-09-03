from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.egress.classification import validated_classification
from core.providers.agentic_adapter import RuntimeTurnContext
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.hosted_agentic_policy import hosted_egress_policy
from core.runtime.attachment_projection import RuntimeAttachmentReadFence
from core.runtime.confined_filesystem import FilesystemResourceObservation
from core.runtime.provider_input_context import (
    RuntimeProviderInputSource,
    runtime_provider_input_sources,
)
from core.runtime.tool_catalog import RuntimeToolCatalog
from tests.support.hosted_agentic_harness import HostedAgenticHarness


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
                    "expected_resource_identity": "linux:1:2",
                    "expected_resource_revision": "a" * 64,
                    "expected_resource_digest": "b" * 64,
                },
            },
            capability_modality="application/pdf",
            projection_mode="workspace_reference",
            attachment_read_fence=RuntimeAttachmentReadFence(
                workspace_relative_path="attachments/evidence.pdf",
                read_encoding="base64",
                resource_identity="linux:1:2",
                resource_revision="a" * 64,
                resource_digest="b" * 64,
            ),
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
        self.assertEqual(
            projection["projection"]["expected_resource_identity"],
            "linux:1:2",
        )
        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "attachment_projection_not_supported",
        ):
            self._request(
                harness,
                replace(
                    context,
                    input_sources=(replace(source, attachment_read_fence=None),),
                ),
            )
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
        file_observation = FilesystemResourceObservation(
            workspace_id="default",
            resource_kind="filesystem_file",
            resource_ref="attachments/benign.txt",
            resource_identity="attachment-file:benign",
            resource_revision="a" * 64,
            resource_digest="a" * 64,
        )
        state = SimpleNamespace(
            inter_agent_store=None,
            workspace_store=None,
            runtime_input_classification_resolver=classify,
        )
        with patch(
            "core.runtime.provider_input_context._attachment_observation",
            return_value=(file_observation, file_classification),
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
