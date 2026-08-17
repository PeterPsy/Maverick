from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.providers.certification_pipeline import (
    execute_certification_suite,
    sign_certification_run,
    verify_certification_run,
)
from core.providers.errors import CapabilityCertificateError


class CertificationPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[3]
        self.artifact = self.root / "tests/unit/providers/test_certification_pipeline.py"
        self.matrix = self.root / "docs/reference/google_agentic_certification_matrix.md"
        self.digest = "a" * 64
        self.started_at = datetime(2026, 8, 17, tzinfo=UTC)

    def test_successful_executed_suite_can_be_signed_and_verified(self) -> None:
        run = self._execute(("python3", "-c", "print('passed')"))
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
        with self.assertRaisesRegex(CapabilityCertificateError, "certification_suite_failed"):
            self._execute(("python3", "-c", "raise SystemExit(2)"))

    def test_tampered_or_untrusted_run_is_rejected(self) -> None:
        run = self._execute(("python3", "-c", "pass"))
        private_key = Ed25519PrivateKey.generate()
        signed = sign_certification_run(run, signer_key_id="ci-2026", private_key=private_key)
        tampered = replace(signed, run=replace(run, matrix_revision="other"))

        with self.assertRaisesRegex(CapabilityCertificateError, "certification_signature_invalid"):
            verify_certification_run(tampered, trusted_keys={"ci-2026": private_key.public_key()})
        with self.assertRaisesRegex(CapabilityCertificateError, "certification_signer_untrusted"):
            verify_certification_run(signed, trusted_keys={})

    def test_artifact_bundle_must_be_real_and_source_owned(self) -> None:
        with tempfile.NamedTemporaryFile() as outside:
            with self.assertRaisesRegex(
                CapabilityCertificateError,
                "certification_artifact_outside_source",
            ):
                execute_certification_suite(
                    command=("python3", "-c", "pass"), cwd=self.root,
                    suite_id="suite", suite_version="1",
                    adapter_artifact_digest=self.digest,
                    artifact_paths=(Path(outside.name),), matrix_path=self.matrix,
                    matrix_revision="revision", evidence_refs=("platform-evidence:test",),
                    started_at=self.started_at,
                )

    def _execute(self, command: tuple[str, ...]):
        return execute_certification_suite(
            command=command, cwd=self.root, suite_id="suite", suite_version="1",
            adapter_artifact_digest=self.digest, artifact_paths=(self.artifact,),
            matrix_path=self.matrix, matrix_revision="revision",
            evidence_refs=("platform-evidence:test-run:result",),
            started_at=self.started_at,
        )


if __name__ == "__main__":
    unittest.main()
