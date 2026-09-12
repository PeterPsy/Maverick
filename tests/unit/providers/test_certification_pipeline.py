from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import tempfile
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
    ANTIGRAVITY_AGENTIC_CERTIFICATION_MANIFEST,
    GOOGLE_AGENTIC_CERTIFICATION_MANIFEST,
    OPENROUTER_AGENTIC_CERTIFICATION_MANIFEST,
)
from core.runtime.execution_binding import canonical_digest


from tests.support.certification_evidence import fixture_step_process, with_fixture_behavior

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
        secret = "sk-live-secret-must-not-be-retained"
        failed = mock.Mock(
            returncode=2,
            stdout=(
                b'{"reason_code":"provider_authentication_failed",'
                b'"request_count":0,'
                b'"failure_diagnostic":"transport_response_invalid"}'
            ),
            stderr=(
                "FAIL: test_rejects_missing_certificate "
                "(tests.unit.providers.test_example.ExampleTest.test_rejects_missing_certificate)\n"
                "Traceback\nCapabilityCertificateError: provider_authentication_failed\n"
                f"Authorization: Bearer {secret}\n"
                "Ran 12 tests in 0.1s\n\nFAILED (failures=1, skipped=2)\n"
            ).encode(),
        )
        with tempfile.TemporaryDirectory() as folder:
            failure_artifact = Path(folder) / "failed.json"
            with mock.patch("core.providers.certification_pipeline._require_clean_checkout"), mock.patch(
                "core.providers.certification_pipeline._git_commit", return_value="a" * 40
            ), mock.patch("core.providers.certification_pipeline.subprocess.run", return_value=failed):
                with self.assertRaisesRegex(CapabilityCertificateError, "certification_step_failed"):
                    self._execute_unpatched(failure_artifact_path=failure_artifact)

            payload = json.loads(failure_artifact.read_text())
            self.assertEqual(payload["schema_version"], "maverick.agentic-certification-failure.v1")
            self.assertEqual(payload["step_id"], "contract-suite")
            self.assertEqual(payload["exit_code"], 2)
            self.assertEqual(
                payload["diagnostic"]["reason_codes"],
                ["provider_authentication_failed"],
            )
            self.assertEqual(
                payload["diagnostic"]["failed_tests"],
                [
                    "tests.unit.providers.test_example.ExampleTest."
                    "test_rejects_missing_certificate"
                ],
            )
            self.assertEqual(
                payload["diagnostic"]["unittest_summary"],
                {"failures": 1, "skipped": 2, "tests": 12},
            )
            self.assertEqual(
                payload["diagnostic"]["safe_json"]["failure_diagnostic"],
                "transport_response_invalid",
            )
            self.assertNotIn(secret, failure_artifact.read_text())
            self.assertNotIn("stdout", payload)
            self.assertNotIn("stderr", payload)

    def test_fixture_environment_is_synthetic_and_live_environment_is_explicit(self) -> None:
        captured_environments = []

        def capture(*args, **kwargs):
            captured_environments.append(dict(kwargs["env"]))
            return fixture_step_process(args[0], **kwargs)

        supplied = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/production/home",
            "MAVERICK_CONTROL_STORE": "json",
            "MAVERICK_JSON_CONTROL_STORE_ROOT": "/production/control-plane",
            "MAVERICK_GOOGLE_CERTIFICATION_API_KEY": "google-secret",
            "OPENROUTER_API_KEY": "openrouter-secret",
            "MAVERICK_CERTIFICATION_ALLOW_LIVE": "1",
        }
        with mock.patch("core.providers.certification_pipeline._require_clean_checkout"), mock.patch(
            "core.providers.certification_pipeline._git_commit", return_value="a" * 40
        ), mock.patch(
            "core.providers.certification_pipeline.subprocess.run", side_effect=capture
        ):
            execute_certification_suite(
                cwd=self.root,
                suite_id=self.suite_id,
                suite_version=self.suite_version,
                adapter_artifact_digest=self.digest,
                evidence_refs=("platform-evidence:test-run:result",),
                started_at=self.started_at,
                environment=supplied,
            )

        fixture_environment, live_environment = captured_environments
        self.assertEqual(fixture_environment["MAVERICK_CERTIFICATION_ALLOW_LIVE"], "0")
        self.assertNotIn("MAVERICK_CONTROL_STORE", fixture_environment)
        self.assertNotIn("MAVERICK_JSON_CONTROL_STORE_ROOT", fixture_environment)
        self.assertNotIn("MAVERICK_LOCAL_STATE_ROOT", fixture_environment)
        self.assertNotIn("MAVERICK_BOOTSTRAP_SECRET_STORE_ROOT", fixture_environment)
        self.assertNotEqual(fixture_environment["HOME"], supplied["HOME"])
        self.assertNotEqual(
            fixture_environment["TMPDIR"], fixture_environment["HOME"]
        )
        self.assertFalse(Path(fixture_environment["HOME"]).exists())
        self.assertNotIn("MAVERICK_GOOGLE_CERTIFICATION_API_KEY", fixture_environment)
        self.assertNotIn("OPENROUTER_API_KEY", fixture_environment)
        self.assertEqual(
            live_environment["MAVERICK_GOOGLE_CERTIFICATION_API_KEY"],
            "google-secret",
        )
        self.assertEqual(live_environment["OPENROUTER_API_KEY"], "openrouter-secret")
        self.assertEqual(live_environment["MAVERICK_CERTIFICATION_ALLOW_LIVE"], "1")

    def test_green_process_without_live_receipt_is_not_evidence(self) -> None:
        green = mock.Mock(returncode=0, stdout=b"passed", stderr=b"Ran 1 test in 0.1s\n\nOK\n")
        with tempfile.TemporaryDirectory() as folder:
            failure_artifact = Path(folder) / "failed.json"
            with mock.patch("core.providers.certification_pipeline._require_clean_checkout"), mock.patch(
                "core.providers.certification_pipeline._git_commit", return_value="a" * 40
            ), mock.patch("core.providers.certification_pipeline.subprocess.run", return_value=green):
                with self.assertRaisesRegex(CapabilityCertificateError, "certification_json_invalid"):
                    self._execute_unpatched(failure_artifact_path=failure_artifact)

            payload = json.loads(failure_artifact.read_text())
            self.assertEqual(payload["step_id"], "live-provider-probe")
            self.assertEqual(payload["failure_reason"], "certification_json_invalid")

    def test_timed_out_step_writes_hash_only_failure_artifact(self) -> None:
        timeout = subprocess.TimeoutExpired(
            cmd=("python3", "fixture.py"),
            timeout=1800,
            output=b"partial-sensitive-output",
            stderr=b"CapabilityCertificateError: provider_timeout\n",
        )
        with tempfile.TemporaryDirectory() as folder:
            failure_artifact = Path(folder) / "failed.json"
            with mock.patch("core.providers.certification_pipeline._require_clean_checkout"), mock.patch(
                "core.providers.certification_pipeline._git_commit", return_value="a" * 40
            ), mock.patch(
                "core.providers.certification_pipeline.subprocess.run", side_effect=timeout
            ):
                with self.assertRaisesRegex(CapabilityCertificateError, "certification_step_timeout"):
                    self._execute_unpatched(failure_artifact_path=failure_artifact)

            payload = json.loads(failure_artifact.read_text())
            self.assertIsNone(payload["exit_code"])
            self.assertEqual(payload["diagnostic"]["reason_codes"], ["provider_timeout"])
            self.assertNotIn("partial-sensitive-output", failure_artifact.read_text())

    def test_protocol_success_without_natural_behavior_cannot_be_signed(self) -> None:
        run = self._execute(complete_behavior=False)
        with self.assertRaisesRegex(CapabilityCertificateError, "certification_behavior_required"):
            sign_certification_run(run, signer_key_id="test", private_key=Ed25519PrivateKey.generate())

    def test_signed_natural_observations_are_bound_to_the_summary(self) -> None:
        run = self._execute()
        private_key = Ed25519PrivateKey.generate()
        signed = sign_certification_run(run, signer_key_id="test", private_key=private_key)
        from copy import deepcopy

        tampered = deepcopy(signed)
        tampered.run.behavioral_evidence["counters"]["false_classifications"] = 1
        with self.assertRaisesRegex(CapabilityCertificateError, "certification_result_summary_mismatch"):
            verify_certification_run(tampered, trusted_keys={"test": private_key.public_key()})

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
            "antigravity-cli": (
                "python3",
                "scripts/run_antigravity_native_probe.py",
            ),
        }
        expected_command_digests = {
            ("google-ai-studio", "fixture_contract"): (
                "ba2571a5f26e87ba78a705de5d2e5fc159222e7c20730693a7bc5e48b0e456ea"
            ),
            ("google-ai-studio", "live_probe"): (
                "6e87e7eedd24ced63932645004a28ff6d95142b326b984856ad27d393b039579"
            ),
            ("openrouter", "fixture_contract"): (
                "592140fd8625e7b4cb1e07bd8ff6418f21f6694c9081fad2a61e15abe0f4413b"
            ),
            ("openrouter", "live_probe"): (
                "3d92023995880fff3a1aad33cdb1a335cc6da438acb8361ee403e1b832afaccd"
            ),
            ("antigravity-cli", "fixture_contract"): (
                "1177ce520ea8997171b01388ccf6fc72a20ddcfffcbc873961c8af197f7ee99c"
            ),
            ("antigravity-cli", "live_probe"): (
                "0dfccc774ce0bb02dfa12244512748e2e85b8c913d975fd23c6d02cbe9284b63"
            ),
        }
        expected_manifest_digests = {
            "google-ai-studio": "6d6a9775682df8e4a1fed02b514cbd0ca799af76173cd32c2abb7e3dc5b90436",
            "openrouter": "064d0927d3fdeda854771a83b42926ab868da485062ef7da442ab888e17c0aa3",
            "antigravity-cli": "e08f621beef114376eeab860bb7b1041c26a6da7530e8efae4cb012d95c73516",
        }
        for manifest in (
            GOOGLE_AGENTIC_CERTIFICATION_MANIFEST,
            OPENROUTER_AGENTIC_CERTIFICATION_MANIFEST,
            ANTIGRAVITY_AGENTIC_CERTIFICATION_MANIFEST,
        ):
            with self.subTest(provider_id=manifest.provider_id):
                self.assertEqual(manifest.suite_version, "64")
                self.assertEqual(
                    manifest.matrix_revision,
                    "2026-09-12-r64-openrouter-glm-full-workspace-relace-tcb54",
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
                for required in (
                    "tests.unit.recovery.test_continuation_fork",
                    "tests.unit.recovery.test_continuation_repair",
                    "tests.unit.recovery.test_continuation_multihop",
                    "tests.unit.recovery.test_continuation_native_identity",
                    "tests.unit.providers.test_antigravity_cli_concurrency",
                    "tests.unit.providers.test_antigravity_cli_discovery",
                    "tests.unit.providers.test_antigravity_cli_runtime_home",
                    "tests.unit.scripts.test_antigravity_native_probe",
                    "tests.integration.cli_mcp.test_builtin_surface_effects",
                    "tests.integration.cli_mcp.test_p6_effect_audit_delta",
                ):
                    self.assertIn(required, manifest.steps[0].command)
                for step in manifest.steps:
                    self.assertEqual(
                        canonical_digest(step.command),
                        expected_command_digests[(manifest.provider_id, step.kind)],
                    )

    def _execute(self, *, step_kinds: tuple[str, ...] | None = None, complete_behavior=True):
        with mock.patch("core.providers.certification_pipeline._require_clean_checkout"), mock.patch(
            "core.providers.certification_pipeline._git_commit", return_value="a" * 40
        ), mock.patch(
            "core.providers.certification_pipeline.subprocess.run",
            side_effect=fixture_step_process,
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
        return with_fixture_behavior(result) if step_kinds is None and complete_behavior else result

    def _execute_unpatched(
        self,
        *,
        step_kinds: tuple[str, ...] | None = None,
        failure_artifact_path: Path | None = None,
    ):
        return execute_certification_suite(
            cwd=self.root, suite_id=self.suite_id, suite_version=self.suite_version,
            adapter_artifact_digest=self.digest,
            evidence_refs=("platform-evidence:test-run:result",),
            started_at=self.started_at,
            step_kinds=step_kinds,
            failure_artifact_path=failure_artifact_path,
        )


if __name__ == "__main__":
    unittest.main()
