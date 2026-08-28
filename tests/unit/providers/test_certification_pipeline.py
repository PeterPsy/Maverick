from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import unittest
from unittest import mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.providers.certification_pipeline import (
    SignedCertificationRun,
    execute_certification_suite,
    sign_certification_run,
    validate_run_against_manifest,
    verify_certification_run,
)
from core.providers.errors import CapabilityCertificateError
from core.providers.google_agentic_certification import GOOGLE_CERTIFICATION_SUITE_VERSION
from core.providers.certification_manifests import (
    GOOGLE_AGENTIC_CERTIFICATION_MANIFEST,
    OPENROUTER_AGENTIC_CERTIFICATION_MANIFEST,
)
from core.runtime.execution_binding import canonical_digest


class CertificationPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[3]
        self.suite_id = "maverick-google-interactions-agentic-contract"
        self.suite_version = GOOGLE_CERTIFICATION_SUITE_VERSION
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

    def test_fixture_only_run_cannot_be_signed_or_verified(self) -> None:
        run = self._execute(step_kinds=("fixture_contract",))
        private_key = Ed25519PrivateKey.generate()

        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "certification_required_steps_missing",
        ):
            sign_certification_run(
                run,
                signer_key_id="ci-2026",
                private_key=private_key,
            )

        unsigned_fixture_claim = SignedCertificationRun(
            run=run,
            signer_key_id="ci-2026",
            signature="not-certificate-evidence",
        )
        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "certification_required_steps_missing",
        ):
            verify_certification_run(
                unsigned_fixture_claim,
                trusted_keys={"ci-2026": private_key.public_key()},
            )

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

    def test_tcb_drift_blocks_signing_verification_and_publication_validation(self) -> None:
        run = self._execute()
        private_key = Ed25519PrivateKey.generate()
        signed = sign_certification_run(
            run,
            signer_key_id="ci-2026",
            private_key=private_key,
            cwd=self.root,
        )

        with self._simulated_generalist_context_drift():
            with self.assertRaisesRegex(CapabilityCertificateError, "certificate_tcb_drift"):
                sign_certification_run(
                    run,
                    signer_key_id="ci-2026",
                    private_key=private_key,
                    cwd=self.root,
                )
            with self.assertRaisesRegex(CapabilityCertificateError, "certificate_tcb_drift"):
                verify_certification_run(
                    signed,
                    trusted_keys={"ci-2026": private_key.public_key()},
                    cwd=self.root,
                )
            with self.assertRaisesRegex(CapabilityCertificateError, "certificate_tcb_drift"):
                validate_run_against_manifest(
                    run,
                    cwd=self.root,
                    deployed_source_commit=run.source_commit,
                )

    def _simulated_generalist_context_drift(self):
        target = (self.root / "core/inter_agent/generalist_context.py").resolve()
        original_read_bytes = Path.read_bytes

        def drifted_read_bytes(path: Path) -> bytes:
            content = original_read_bytes(path)
            if path.resolve() == target:
                return content + b"\n# stale-certified-generalist-context\n"
            return content

        return mock.patch.object(Path, "read_bytes", drifted_read_bytes)

    def test_unknown_suite_cannot_supply_an_arbitrary_command(self) -> None:
        with self.assertRaisesRegex(CapabilityCertificateError, "manifest_unknown"):
            execute_certification_suite(
                cwd=self.root, suite_id="arbitrary", suite_version="1",
                adapter_artifact_digest=self.digest,
                evidence_refs=("platform-evidence:test",), started_at=self.started_at,
            )

    def test_remote_manifests_bind_fixture_and_live_probe_commands(self) -> None:
        expected_live_commands = {
            "google-ai-studio": (
                "python3",
                "scripts/run_google_interactions_probe.py",
            ),
            "openrouter": (
                "python3",
                "scripts/run_openrouter_agentic_probe.py",
            ),
        }
        expected_command_digests = {
            ("google-ai-studio", "fixture_contract"): (
                "9fc214ee2e4e5e006ebf5e8a3d3d41dd9a4f18cc1d67b52ab206c3a63993e8c0"
            ),
            ("google-ai-studio", "live_probe"): (
                "6e87e7eedd24ced63932645004a28ff6d95142b326b984856ad27d393b039579"
            ),
            ("openrouter", "fixture_contract"): (
                "ea1d08540c5b9188a403213cb5300866b461fa670273308e354c4e16450f986b"
            ),
            ("openrouter", "live_probe"): (
                "3d92023995880fff3a1aad33cdb1a335cc6da438acb8361ee403e1b832afaccd"
            ),
        }
        expected_manifest_digests = {
            "google-ai-studio": (
                "fe5a83578ad575d2fac3afdf5467657d289f81d301223889bb9219590ce10437"
            ),
            "openrouter": (
                "ed324773d4beaab44902d504c12443d5286b8a7ae66612cd9adb6e98677d9564"
            ),
        }
        for manifest in (
            GOOGLE_AGENTIC_CERTIFICATION_MANIFEST,
            OPENROUTER_AGENTIC_CERTIFICATION_MANIFEST,
        ):
            with self.subTest(provider_id=manifest.provider_id):
                self.assertEqual(
                    manifest.matrix_revision,
                    "2026-08-28-r15-p3-review3-tcb5",
                )
                self.assertEqual(
                    manifest.digest,
                    expected_manifest_digests[manifest.provider_id],
                )
                self.assertEqual(
                    tuple(step.kind for step in manifest.steps),
                    ("fixture_contract", "live_probe"),
                )
                self.assertEqual(
                    manifest.steps[1].command,
                    expected_live_commands[manifest.provider_id],
                )
                for step in manifest.steps:
                    self.assertEqual(
                        canonical_digest(step.command),
                        expected_command_digests[(manifest.provider_id, step.kind)],
                    )

    def _execute(self, *, step_kinds: tuple[str, ...] | None = None):
        passed = mock.Mock(returncode=0, stdout=b"passed", stderr=b"")
        with mock.patch("core.providers.certification_pipeline._require_clean_checkout"), mock.patch(
            "core.providers.certification_pipeline._git_commit", return_value="a" * 40
        ), mock.patch(
            "core.providers.certification_pipeline.subprocess.run",
            return_value=passed,
        ) as run_subprocess:
            result = self._execute_unpatched(step_kinds=step_kinds)
        expected_steps = [
            step
            for step in GOOGLE_AGENTIC_CERTIFICATION_MANIFEST.steps
            if step_kinds is None or step.kind in step_kinds
        ]
        self.assertEqual(
            [call.args[0] for call in run_subprocess.call_args_list],
            [step.command for step in expected_steps],
        )
        self.assertEqual(
            [item["command_digest"] for item in result.step_results],
            [canonical_digest(step.command) for step in expected_steps],
        )
        return result

    def _execute_unpatched(self, *, step_kinds: tuple[str, ...] | None = None):
        return execute_certification_suite(
            cwd=self.root, suite_id=self.suite_id, suite_version=self.suite_version,
            adapter_artifact_digest=self.digest,
            evidence_refs=("platform-evidence:test-run:result",),
            started_at=self.started_at,
            step_kinds=step_kinds,
        )


if __name__ == "__main__":
    unittest.main()
