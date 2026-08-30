from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import os
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.egress import AgenticEgressContentBlock, public_remote_egress_policy
from core.egress.agentic_transforms import canonical_egress_content
from core.runtime.provider_input_context import (
    RuntimeProviderInputObservation,
    runtime_provider_input_sources,
)
from core.runtime.provider_input_admission import (
    GOVERNED_CONTEXT_SOURCE_RESOURCE_KIND,
)
from core.workspaces.data_governance import WorkspaceResourceClassification
from tests.support.hosted_agentic_harness import HostedAgenticHarness


NOW = datetime(2026, 8, 28, tzinfo=UTC)


class RuntimeProviderInputAdmissionTest(unittest.TestCase):
    def test_production_input_admission_never_promotes_unclassified_bytes(self) -> None:
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

        sources = runtime_provider_input_sources(
            state,
            session=harness.session,
            turn_id="turn-sensitive",
            input_text="customer SSN 123-45-6789",
            app_references=None,
            attachments=None,
        )

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].classification.data_class, "unclassified")
        self.assertEqual(
            sources[0].classification.trust_level,
            "untrusted_external",
        )
        governed = {"tasks": [{"result_summary": "customer SSN 123-45-6789"}]}
        digest = hashlib.sha256(canonical_egress_content(governed)).hexdigest()
        governed_classification = state.runtime_input_classification_resolver(
            RuntimeProviderInputObservation(
                workspace_id=harness.session.workspace_id,
                session_id=harness.session.session_id,
                turn_id="turn-sensitive",
                source_id="generalist-orchestration",
                provenance="governed_context",
                content_type="application/json",
                source_ref=(
                    "runtime-turn:turn-sensitive:generalist-orchestration"
                ),
                source_revision=digest,
                source_digest=digest,
                resource_identity=(
                    f"runtime-input:{harness.session.workspace_id}:"
                    f"{harness.session.session_id}:turn-sensitive:"
                    f"generalist-orchestration:{digest}"
                ),
            ),
            governed,
        )
        self.assertEqual(governed_classification.data_class, "unclassified")
        self.assertEqual(
            governed_classification.trust_level,
            "untrusted_external",
        )
        egress = state.agentic_egress_evaluator.evaluate(
            block=AgenticEgressContentBlock(
                content_block_id="governed-context-sensitive",
                session_id=harness.session.session_id,
                turn_id="turn-sensitive",
                workspace_id=harness.session.workspace_id,
                data_class=governed_classification.data_class,
                provenance="governed_context",
                trust_level=governed_classification.trust_level,
                content_type="application/json",
                source_ref=governed_classification.source_ref,
                source_revision=governed_classification.source_revision,
                resource_identity=governed_classification.resource_identity,
                classification_revision=(
                    governed_classification.classification_revision
                ),
            ),
            content=governed,
            destination_provider_id="google-ai-studio",
            destination_upstream_id=None,
            policy=public_remote_egress_policy(
                provider_id="google-ai-studio"
            ),
            persist=False,
        )
        self.assertFalse(egress.decision.export_allowed)
        self.assertIsNone(egress.exported_content)

    def test_governed_context_restrictively_joins_its_source_records(self) -> None:
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
        chunks = (
            (
                "inter-agent-run:run-sensitive:control",
                {
                    "run_id": "run-sensitive",
                    "status": "running",
                    "progress": {"total_tasks": 1},
                    "quality_gate": {"status": "pending"},
                    "task_count": 1,
                    "artifact_count": 0,
                },
                "public",
            ),
            (
                "inter-agent-run:run-sensitive:summary",
                {"summary": "fixture orchestration"},
                "public",
            ),
            (
                "inter-agent-run:run-sensitive:task:task-sensitive",
                governed["tasks"][0],
                "personal_data",
            ),
        )
        for index, (resource_ref, content, data_class) in enumerate(chunks):
            digest = hashlib.sha256(canonical_egress_content(content)).hexdigest()
            state.workspace_store.save_resource_classification(
                WorkspaceResourceClassification(
                    classification_id=f"classification-governed-{index}",
                    workspace_id=harness.session.workspace_id,
                    resource_kind=GOVERNED_CONTEXT_SOURCE_RESOURCE_KIND,
                    resource_ref=resource_ref,
                    resource_identity=(
                        f"governed-context-source:{harness.session.workspace_id}:"
                        f"{resource_ref}:{digest}"
                    ),
                    resource_revision=digest,
                    resource_digest=digest,
                    data_class=data_class,
                    trust_level="untrusted_external",
                    revision=1,
                    classified_by_actor_id="fixture-classifier",
                    classified_at=NOW,
                    updated_at=NOW,
                ),
                expected_revision=0,
            )
        digest = hashlib.sha256(canonical_egress_content(governed)).hexdigest()
        classification = state.runtime_input_classification_resolver(
            RuntimeProviderInputObservation(
                workspace_id=harness.session.workspace_id,
                session_id=harness.session.session_id,
                turn_id="turn-sensitive",
                source_id="generalist-orchestration",
                provenance="governed_context",
                content_type="application/json",
                source_ref=(
                    "runtime-turn:turn-sensitive:generalist-orchestration"
                ),
                source_revision=digest,
                source_digest=digest,
                resource_identity=(
                    f"runtime-input:{harness.session.workspace_id}:"
                    f"{harness.session.session_id}:turn-sensitive:"
                    f"generalist-orchestration:{digest}"
                ),
            ),
            governed,
        )

        self.assertEqual(classification.data_class, "personal_data")
        self.assertEqual(classification.trust_level, "untrusted_external")


if __name__ == "__main__":
    unittest.main()
