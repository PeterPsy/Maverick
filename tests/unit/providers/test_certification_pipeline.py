from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import unittest
from unittest import mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.providers.certification_pipeline import (
    execute_certification_suite,
    sign_certification_run,
    validate_run_against_manifest,
    verify_certification_run,
)
from core.providers.errors import CapabilityCertificateError


class CertificationPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[3]
        self.suite_id = "maverick-google-interactions-agentic-contract"
        self.suite_version = "5"
        self.digest = "a" * 64
        self.started_at = datetime(2026, 8, 17, tzinfo=UTC)

    def test_successful_executed_suite_can_be_signed_and_verified(self) -> None:
        run = self._execute()
        private_key = Ed25519PrivateKey.generate()
        signed = sign_certification_run(run, signer_key_id="ci-2026", private_key=private_key)

        verified = verify_certification_run(
            signed,
            trusted_keys={"ci-2026": private_key.public_key()},
        )

        self.assertEqual(verified.outcome, "passed")
        self.assertTrue(verified.test_run_id.startswith("run:"))
        self.assertEqual(len(verified.source_commit), 40)
        self.assertEqual(len(verified.artifact_bundle_digest), 64)

    def test_failed_suite_emits_no_run_result(self) -> None:
        failed = mock.Mock(returncode=2, stdout=b"", stderr=b"failed")
        with mock.patch("core.providers.certification_pipeline._require_clean_checkout"), mock.patch(
            "core.providers.certification_pipeline._git_commit", return_value="a" * 40
        ), mock.patch("core.providers.certification_pipeline.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(CapabilityCertificateError, "certification_step_failed"):
                self._execute_unpatched()

    def test_tampered_or_untrusted_run_is_rejected(self) -> None:
        run = self._execute()
        private_key = Ed25519PrivateKey.generate()
        signed = sign_certification_run(run, signer_key_id="ci-2026", private_key=private_key)
        tampered = replace(signed, run=replace(run, matrix_revision="other"))

        with self.assertRaisesRegex(CapabilityCertificateError, "certification_signature_invalid"):
            verify_certification_run(tampered, trusted_keys={"ci-2026": private_key.public_key()})
        with self.assertRaisesRegex(CapabilityCertificateError, "certification_signer_untrusted"):
            verify_certification_run(signed, trusted_keys={})

    def test_publisher_rejects_a_different_deployed_commit(self) -> None:
        run = self._execute()
        with self.assertRaisesRegex(CapabilityCertificateError, "source_commit_mismatch"):
            validate_run_against_manifest(
                run, cwd=self.root, deployed_source_commit="b" * 40
            )

    def test_unknown_suite_cannot_supply_an_arbitrary_command(self) -> None:
        with self.assertRaisesRegex(CapabilityCertificateError, "manifest_unknown"):
            execute_certification_suite(
                cwd=self.root, suite_id="arbitrary", suite_version="1",
                adapter_artifact_digest=self.digest,
                evidence_refs=("platform-evidence:test",), started_at=self.started_at,
            )

    def _execute(self):
        passed = mock.Mock(returncode=0, stdout=b"passed", stderr=b"")
        with mock.patch("core.providers.certification_pipeline._require_clean_checkout"), mock.patch(
            "core.providers.certification_pipeline._git_commit", return_value="a" * 40
        ), mock.patch("core.providers.certification_pipeline.subprocess.run", return_value=passed):
            return self._execute_unpatched()

    def _execute_unpatched(self):
        return execute_certification_suite(
            cwd=self.root, suite_id=self.suite_id, suite_version=self.suite_version,
            adapter_artifact_digest=self.digest,
            evidence_refs=("platform-evidence:test-run:result",),
            started_at=self.started_at,
        )


if __name__ == "__main__":
    unittest.main()
