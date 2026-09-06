"""Signatures cannot replace retained bytes or publisher-owned independent trust."""

from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.cli.certification_publication_commands import certification_publication_command_specs
from core.cli.models import CliInvocationContext
from core.providers.certification_artifacts import canonical_artifact, retained_run_references
from core.providers.certification_pipeline import execute_certification_suite, sign_certification_run
from core.providers.certification_summary import certification_result_summary
from core.providers.certification_target import builtin_api_certification_profile
from core.providers.errors import CapabilityCertificateError
from core.providers.google_agentic_certification import (
    GOOGLE_CERTIFICATION_SUITE_ID, GOOGLE_CERTIFICATION_SUITE_VERSION, publish_google_preview_certificate,
)
from core.runtime.execution_binding import canonical_digest
from tests.support.certification_evidence import fixture_step_process, with_fixture_behavior, fixture_publication_authority


class CertificationPublicationTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[3]
        with patch("core.providers.certification_pipeline._require_clean_checkout"), patch(
            "core.providers.certification_pipeline._git_commit", return_value="a" * 40,
        ), patch("core.providers.certification_pipeline.subprocess.run", side_effect=fixture_step_process):
            run = execute_certification_suite(
                cwd=self.root, suite_id=GOOGLE_CERTIFICATION_SUITE_ID, suite_version=GOOGLE_CERTIFICATION_SUITE_VERSION,
                adapter_artifact_digest="a" * 64, evidence_refs=(), started_at=datetime.now(UTC),
            )
        self.run = with_fixture_behavior(run)
        self.key = Ed25519PrivateKey.generate()
        self.signed = sign_certification_run(self.run, signer_key_id="worker", private_key=self.key)
        self.publisher, self.review = fixture_publication_authority(self, self.signed, self.key)

    def verify(self, signed=None, review=None):
        return self.publisher.verify(signed or self.signed, review or self.review, cwd=self.root)

    def test_complete_retained_run_and_independent_review_are_verified(self):
        run, refs = self.verify()
        self.assertEqual(run, self.run)
        self.assertGreater(len(refs), len(run.evidence_refs))
        report = canonical_artifact(run.behavioral_evidence)
        self.assertEqual(self.publisher.evidence_store.get(run.evidence_refs[-1]), report)

    def test_every_missing_or_corrupted_observation_blob_denies_before_certificate_write(self):
        for ref in retained_run_references(self.run):
            blob = self.publisher.evidence_store.get(ref)
            digest = ref.rsplit(":", 1)[1]
            path = self.publisher.evidence_store.root / digest[:2] / digest
            for corruption in (None, b"corrupted"):
                with self.subTest(ref=ref, missing=corruption is None):
                    if corruption is None:
                        path.unlink()
                    else:
                        path.write_bytes(corruption)
                    store = Mock()
                    try:
                        with self.assertRaisesRegex(CapabilityCertificateError, "evidence_blob_(missing|corrupt)"):
                            publish_google_preview_certificate(
                                store, definition=builtin_api_certification_profile("google-ai-studio"), adapter=object(),
                                signed_run=self.signed, publisher=self.publisher, review=self.review,
                            )
                        self.assertEqual(store.method_calls, [])
                    finally:
                        path.write_bytes(blob)

    def test_worker_cannot_authorize_a_new_signer(self):
        other = sign_certification_run(self.run, signer_key_id="self-appointed", private_key=Ed25519PrivateKey.generate())
        with self.assertRaisesRegex(CapabilityCertificateError, "signer_untrusted"):
            self.verify(signed=other)
        with self.assertRaisesRegex(CapabilityCertificateError, "signer_untrusted"):
            self.verify(review=replace(self.review, signer_key_id="self-appointed"))

    def test_valid_worker_signature_cannot_replace_observed_step_receipts(self):
        live_receipt = {**self.run.step_results[1]["live_receipt"],
                        "test_run_id": "google-interactions-live:11111111-1111-1111-1111-111111111111"}
        for index, stream, content, reason in (
            (0, "stderr_digest", b"Exception in thread Thread-1:\nRan 1 test in 0.1s\n\nOK\n", "fixture_receipt_invalid"),
            (0, "stderr_digest", b"Ran 2 tests in 0.1s\n\nOK\n", "artifact_receipt_mismatch"),
            (1, "stdout_digest", canonical_artifact(live_receipt), "artifact_receipt_mismatch"),
            (1, "stdout_digest", b"not a live receipt", "certification_json_invalid"),
        ):
            with self.subTest(index=index, reason=reason):
                steps = [dict(step) for step in self.run.step_results]
                steps[index][stream] = self.publisher.evidence_store.put(content).rsplit(":", 1)[1]
                run = replace(self.run, step_results=tuple(steps))
                run = replace(run, result_summary_digest=canonical_digest(certification_result_summary(run)))
                signed = sign_certification_run(run, signer_key_id="worker", private_key=self.key)
                # A trusted collector's valid signature is not sufficient: the
                # actual bytes are rejected before even considering the review.
                with self.assertRaisesRegex(CapabilityCertificateError, reason):
                    self.verify(signed=signed)

    def test_reviewer_key_alias_is_not_independence_and_policy_is_reloaded(self):
        path = self.publisher.trust_policy_path
        policy = json.loads(path.read_text())
        policy["reviewers"]["test-reviewer"]["public_key"] = policy["collectors"]["worker"]["public_key"]
        path.write_text(json.dumps(policy))
        with self.assertRaisesRegex(CapabilityCertificateError, "review_not_independent"):
            self.verify()

    def test_review_is_bound_to_exact_signed_run_and_artifact_set(self):
        for field in ("signed_run_digest", "artifacts_digest"):
            with self.subTest(field=field), self.assertRaisesRegex(CapabilityCertificateError, "review_target_mismatch"):
                self.verify(review=replace(self.review, **{field: "b" * 64}))
        with self.assertRaisesRegex(CapabilityCertificateError, "review_invalid"):
            self.verify(review=replace(self.review, signature="not a signature"))

    def test_operational_surface_is_operator_only_and_does_not_take_trust_keys(self):
        definition, handler = certification_publication_command_specs()[0]
        self.assertTrue(definition.invocation_policy.operator_only)
        self.assertNotIn("trusted_keys", definition.argument_schema["properties"])
        result = handler({}, CliInvocationContext(caller_kind="full_access_agent", user_id="admin",
                         workspace_id="default", agent_id="chat", effective_mode="full-access", platform_role="admin"))
        self.assertEqual(result["error"], "certification_operator_required")


if __name__ == "__main__":
    unittest.main()
