from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import os
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.egress import AgenticEgressContentBlock, public_remote_egress_policy
from core.egress.agentic_transforms import canonical_egress_content
from core.runtime.provider_input_capture import (
    RuntimeProviderInputCaptureSource,
    capture_runtime_provider_input_classifications,
    classify_runtime_provider_input_content,
)
from core.runtime.provider_input_context import (
    RuntimeProviderInputObservation,
    runtime_provider_input_sources,
)
from core.runtime.runtime_turns import RuntimeTurnRecord
from tests.support.hosted_agentic_harness import HostedAgenticHarness


NOW = datetime(2026, 8, 28, tzinfo=UTC)


class RuntimeProviderInputAdmissionTest(unittest.TestCase):
    def test_production_capture_classifies_sensitive_prompt_from_exact_bytes(
        self,
    ) -> None:
        harness, state = self._state_with_turn(
            input_text="customer SSN 123-45-6789",
        )

        sources = runtime_provider_input_sources(
            state,
            session=harness.session,
            turn_id="turn-sensitive",
            input_text="customer SSN 123-45-6789",
            app_references=None,
            attachments=None,
        )

        self.assertEqual(len(sources), 1)
        classification = sources[0].classification
        self.assertEqual(
            classification.data_class,
            "regulated_or_customer_data",
        )
        self.assertEqual(classification.trust_level, "trusted_actor")
        persisted = state.runtime_store.get_turn("turn-sensitive")
        self.assertIsNotNone(
            persisted.provider_input_classification_manifest
        )
        egress = state.agentic_egress_evaluator.evaluate(
            block=AgenticEgressContentBlock(
                content_block_id="sensitive-prompt",
                session_id=harness.session.session_id,
                turn_id="turn-sensitive",
                workspace_id=harness.session.workspace_id,
                data_class=classification.data_class,
                provenance="user_input",
                trust_level=classification.trust_level,
                content_type="text/plain",
                source_ref=classification.source_ref,
                source_revision=classification.source_revision,
                resource_identity=classification.resource_identity,
                classification_revision=classification.classification_revision,
            ),
            content="customer SSN 123-45-6789",
            destination_provider_id="google-ai-studio",
            destination_upstream_id=None,
            policy=public_remote_egress_policy(
                provider_id="google-ai-studio"
            ),
            persist=False,
        )
        self.assertFalse(egress.decision.export_allowed)
        self.assertIsNone(egress.exported_content)

    def test_unmarked_prompt_is_captured_as_unclassified(self) -> None:
        harness, state = self._state_with_turn(
            input_text="Summarize the public fixture.",
        )

        sources = runtime_provider_input_sources(
            state,
            session=harness.session,
            turn_id="turn-sensitive",
            input_text="Summarize the public fixture.",
            app_references=None,
            attachments=None,
        )

        self.assertEqual(sources[0].classification.data_class, "unclassified")
        self.assertEqual(sources[0].classification.classification_revision, 2)

    def test_content_scanning_never_promotes_benign_looking_text_to_public(
        self,
    ) -> None:
        for content in (
            "confidential account narrative",
            "employee salary matrix",
            "customer medical diagnosis: lymphoma",
        ):
            with self.subTest(content=content):
                self.assertEqual(
                    classify_runtime_provider_input_content(
                        content,
                        content_type="text/plain",
                    ),
                    "unclassified",
                )

    def test_governed_context_restrictively_joins_captured_source_bytes(
        self,
    ) -> None:
        harness, state = self._state_with_turn(input_text="Review the run.")
        governed = {
            "run_id": "run-sensitive",
            "status": "running",
            "summary": "fixture orchestration",
            "progress": {"total_tasks": 1},
            "quality_gate": {"status": "pending"},
            "tasks": [
                {
                    "task_id": "task-sensitive",
                    "result_summary": "customer SSN 123-45-6789",
                }
            ],
            "artifacts": [],
        }
        sources = runtime_provider_input_sources(
            state,
            session=harness.session,
            turn_id="turn-sensitive",
            input_text="Review the run.",
            app_references=None,
            attachments=None,
            orchestration=governed,
        )
        classification = next(
            source.classification
            for source in sources
            if source.source_id == "generalist-orchestration"
        )

        # The sensitive chunk is detected, but benign-looking sibling chunks
        # remain unclassified and the restrictive aggregate cannot promote
        # them merely because no marker was found.
        self.assertEqual(classification.data_class, "unclassified")
        self.assertEqual(classification.trust_level, "untrusted_external")

    def test_missing_or_conflicting_capture_fails_closed(self) -> None:
        harness, state = self._state_with_turn(input_text="Original prompt")
        observation = self._observation(
            harness,
            source_id="turn-prompt",
            provenance="user_input",
            content_type="text/plain",
            content="Original prompt",
        )
        unresolved = state.runtime_input_classification_resolver(
            observation,
            "Original prompt",
        )
        self.assertEqual(unresolved.data_class, "unclassified")

        with self.assertRaisesRegex(
            ValueError,
            "runtime_provider_input_capture_invalid",
        ):
            capture_runtime_provider_input_classifications(
                state.runtime_store,
                workspace_id=harness.session.workspace_id,
                session_id=harness.session.session_id,
                turn_id="turn-sensitive",
                sources=(
                    RuntimeProviderInputCaptureSource(
                        "turn-prompt",
                        "user_input",
                        "text/plain",
                        "Different prompt",
                    ),
                ),
            )

    def test_capture_writer_enforces_source_contract_and_immutable_manifest(
        self,
    ) -> None:
        harness, state = self._state_with_turn(input_text="Original prompt")
        invalid_source = RuntimeProviderInputCaptureSource(
            "turn-prompt",
            "governed_context",
            "application/json",
            "Original prompt",
        )
        with self.assertRaisesRegex(
            ValueError,
            "runtime_provider_input_capture_invalid",
        ):
            capture_runtime_provider_input_classifications(
                state.runtime_store,
                workspace_id=harness.session.workspace_id,
                session_id=harness.session.session_id,
                turn_id="turn-sensitive",
                sources=(invalid_source,),
            )

        valid_source = RuntimeProviderInputCaptureSource(
            "turn-prompt",
            "user_input",
            "text/plain",
            "Original prompt",
        )
        manifest = capture_runtime_provider_input_classifications(
            state.runtime_store,
            workspace_id=harness.session.workspace_id,
            session_id=harness.session.session_id,
            turn_id="turn-sensitive",
            sources=(valid_source,),
        )
        self.assertEqual(
            capture_runtime_provider_input_classifications(
                state.runtime_store,
                workspace_id=harness.session.workspace_id,
                session_id=harness.session.session_id,
                turn_id="turn-sensitive",
                sources=(valid_source,),
            ),
            manifest,
        )
        conflicting = deepcopy(manifest)
        source_ref = "runtime-turn:turn-sensitive:turn-prompt"
        conflicting["sources"][source_ref]["data_class"] = "public"
        with self.assertRaisesRegex(
            ValueError,
            "runtime_provider_input_capture_conflict",
        ):
            state.runtime_store.capture_turn_provider_input_classification_manifest(
                turn_id="turn-sensitive",
                manifest=conflicting,
            )

    def _state_with_turn(
        self,
        *,
        input_text: str,
    ) -> tuple[HostedAgenticHarness, object]:
        harness = HostedAgenticHarness(self)
        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            state = bootstrap_platform_state(
                start_path=harness.root,
                now=NOW,
                install_builtin_apps=False,
            )
        state.runtime_store.insert_session(harness.session)
        state.runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-sensitive",
                session_id=harness.session.session_id,
                workspace_id=harness.session.workspace_id,
                status="active",
                input_text=input_text,
                created_at=NOW,
                updated_at=NOW,
                started_at=NOW,
                completed_at=None,
                failure_reason=None,
            )
        )
        return harness, state

    @staticmethod
    def _observation(
        harness,
        *,
        source_id: str,
        provenance: str,
        content_type: str,
        content: object,
    ) -> RuntimeProviderInputObservation:
        digest = hashlib.sha256(canonical_egress_content(content)).hexdigest()
        return RuntimeProviderInputObservation(
            workspace_id=harness.session.workspace_id,
            session_id=harness.session.session_id,
            turn_id="turn-sensitive",
            source_id=source_id,
            provenance=provenance,
            content_type=content_type,
            source_ref=f"runtime-turn:turn-sensitive:{source_id}",
            source_revision=digest,
            source_digest=digest,
            resource_identity=(
                f"runtime-input:{harness.session.workspace_id}:"
                f"{harness.session.session_id}:turn-sensitive:"
                f"{source_id}:{digest}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
