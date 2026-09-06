"""P6 natural observations are complete, exact-target and payload-free."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest

from core.providers.certification_behavior import validate_behavioral_evidence
from core.providers.certification_live_receipt import decode_certification_json, validate_live_probe_receipt
from core.providers.certification_fixture_receipt import fixture_receipt, validate_fixture_receipt
from core.providers.certification_target import (
    api_certification_resource_limits, api_profile_target_digest,
    builtin_api_certification_profile, builtin_api_certification_target,
    builtin_api_reasoning_efforts, native_connection_target_digest,
)
from core.providers.errors import CapabilityCertificateError
from tests.support.certification_evidence import fixture_behavior_report, fixture_live_receipt


class CertificationBehaviorTest(unittest.TestCase):
    def setUp(self):
        self.provider = "openrouter"
        self.profile = builtin_api_certification_profile(self.provider)
        self.run = SimpleNamespace(target_digest=builtin_api_certification_target(self.provider),
                                   source_commit="a" * 40, tcb_live_digest="b" * 64)
        self.before = datetime.now(tz=UTC) - timedelta(seconds=1)
        self.report = fixture_behavior_report(self.run, provider_id=self.provider)

    def validate(self, report):
        return validate_behavioral_evidence(
            report, target_digest=self.run.target_digest, source_commit=self.run.source_commit,
            tcb_live_digest=self.run.tcb_live_digest, not_before=self.before, now=datetime.now(tz=UTC),
            reasoning_efforts=builtin_api_reasoning_efforts(self.provider),
            resource_limits=api_certification_resource_limits(self.profile),
        )

    def test_every_natural_scenario_at_every_claimed_effort_is_required(self):
        self.assertEqual(len(self.validate(self.report)), 64)
        for change in ("omit", "duplicate", "false", "wrong_effort", "extra_payload", "resources"):
            report = deepcopy(self.report)
            if change == "omit":
                report["observations"].pop()
            elif change == "duplicate":
                report["observations"][-1] = report["observations"][0]
            elif change == "false":
                report["observations"][0]["checks"]["maverick_identity"] = 1
            elif change == "wrong_effort":
                report["observations"][0]["reasoning_effort"] = "unreviewed"
            elif change == "extra_payload":
                report["observations"][0]["prompt"] = "private prompt must never be signed"
            else:
                report["observations"][0]["resources"]["cost_microusd"] = 10**15
            with self.subTest(change=change), self.assertRaises(CapabilityCertificateError):
                self.validate(report)

    def test_identity_timing_and_every_absolute_counter_fail_closed(self):
        for field in ("target_digest", "source_commit", "tcb_live_digest", "scope", "reviewer_ref"):
            report = deepcopy(self.report)
            report[field] = "wrong"
            with self.subTest(field=field), self.assertRaises(CapabilityCertificateError):
                self.validate(report)
        for field, value in (("started_at", (self.before - timedelta(seconds=1)).isoformat()),
                             ("completed_at", (datetime.now(tz=UTC) + timedelta(days=1)).isoformat())):
            report = deepcopy(self.report)
            report[field] = value
            with self.assertRaisesRegex(CapabilityCertificateError, "time_invalid"):
                self.validate(report)
        for field in self.report["counters"]:
            for value in (1, -1, False):
                report = deepcopy(self.report)
                report["counters"][field] = value
                with self.assertRaisesRegex(CapabilityCertificateError, "absolute_gate_failed"):
                    self.validate(report)

    def test_api_target_pins_all_fields_except_publication_time(self):
        digest = api_profile_target_digest(self.profile)
        self.assertEqual(digest, api_profile_target_digest(replace(self.profile, created_at=datetime.now(tz=UTC))))
        for patch in ({"model_id": "other"}, {"harness_recipe_digest": "f" * 64},
                      {"provider_config_digest": "f" * 64}, {"capability_certificate_id": "other"},
                      {"policy_ceiling": replace(self.profile.policy_ceiling, max_steps_per_turn=2)}):
            self.assertNotEqual(digest, api_profile_target_digest(replace(self.profile, **patch)))

    def test_native_target_requires_approved_runtime_and_full_workspace_connection(self):
        from core.providers.native_agent_builtins import build_gemini_cli_candidate_installation

        with self.assertRaisesRegex(CapabilityCertificateError, "native_target_incomplete"):
            native_connection_target_digest(build_gemini_cli_candidate_installation(), model_provider_id="google")

    def test_live_receipts_reject_green_text_false_counts_payloads_and_replay(self):
        for provider in ("google-ai-studio", "openrouter"):
            receipt = fixture_live_receipt(provider, nonce="1" * 32)
            kwargs = dict(provider_id=provider, target_digest=builtin_api_certification_target(provider), run_nonce="1" * 32)
            self.assertEqual(validate_live_probe_receipt(receipt, **kwargs), receipt)
            for field, value in (("succeeded", 1), ("request_count", 99), ("run_nonce", "2" * 32),
                                 ("target_digest", "e" * 64), ("prompt", "private")):
                with self.subTest(provider=provider, field=field), self.assertRaises(CapabilityCertificateError):
                    validate_live_probe_receipt({**receipt, field: value}, **kwargs)
        for raw in (b"passed", b'{"ok":true,"ok":false}', b'{"cost":NaN}',
                    b'{"cost":1e999}', b'{"cost":-1e999}', b" " * 262_145):
            with self.assertRaises(CapabilityCertificateError):
                decode_certification_json(raw)

    def test_skipped_empty_or_nonstandard_fixture_runs_cannot_certify(self):
        self.assertEqual(fixture_receipt(b"...\nRan 123 tests in 2.50s\n\nOK\n"), {"tests_run": 123, "skipped": 0})
        for footer in (b"passed", b"Ran 0 tests in 0.1s\n\nOK\n",
                       b"Ran 123 tests in 2.5s\n\nOK (skipped=1)\n",
                       b"Ran 123 tests in 2.5s\n\nOK\nextra output\n"):
            with self.assertRaises(CapabilityCertificateError):
                fixture_receipt(footer)
        with self.assertRaises(CapabilityCertificateError):
            validate_fixture_receipt({"tests_run": True, "skipped": 0})


if __name__ == "__main__":
    unittest.main()
