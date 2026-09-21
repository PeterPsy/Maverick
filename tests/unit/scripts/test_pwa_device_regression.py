from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from scripts.pwa_device_regression import (
    WAIVER_SCHEMA,
    evidence_template,
    merge_smoke_progress,
    validate_evidence,
    validate_release_evidence,
)


NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
POLICY = {
    "device_regression": {
        "release_candidate_binding": "exact_release_id",
        "max_evidence_age_days": 90,
        "max_waiver_age_days": 7,
        "required_profiles": ["safari-macos-browser", "safari-iphone-home-screen"],
        "required_scenarios": ["warm-launch", "logout-cleanup"],
    }
}


def valid_evidence() -> dict:
    payload = evidence_template(POLICY, "release-2026-09-05")
    payload.update(
        captured_at=NOW.isoformat(),
        redaction_reviewed=True,
        release_id="release-2026-09-05",
    )
    for run in payload["runs"]:
        run["os_version"] = "physical-os-version"
        run["browser_version"] = "physical-browser-version"
        run["scenarios"] = {name: "pass" for name in POLICY["device_regression"]["required_scenarios"]}
    return payload


def valid_waiver(*, passed: int, pending: int) -> dict:
    return {
        "schema": WAIVER_SCHEMA,
        "accepted_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=2)).isoformat(),
        "release_id": "release-2026-09-05",
        "scope": "single-release-candidate",
        "release_owner_approved": True,
        "risk_acceptance": "remaining-physical-coverage",
        "observed_results": {
            "pass": passed,
            "fail": 0,
            "pending": pending,
            "total": passed + pending,
        },
    }


class PwaDeviceRegressionTests(unittest.TestCase):
    def test_merges_only_observed_smoke_results_into_progress(self) -> None:
        smoke = {
            "schema": "maverick.pwa-physical-browser-smoke.v1",
            "captured_at": NOW.isoformat(),
            "environment": "physical-device",
            "redaction_reviewed": True,
            "release_id": "release-2026-09-05",
            "profile": "safari-macos-browser",
            "os_version": "physical-os-version",
            "browser_version": "physical-browser-version",
            "scenarios": {"warm-launch": "pass", "logout-cleanup": "not-run"},
        }

        payload, summary = merge_smoke_progress(POLICY, "release-2026-09-05", [smoke])

        safari = next(run for run in payload["runs"] if run["profile"] == "safari-macos-browser")
        home_screen = next(run for run in payload["runs"] if run["profile"] == "safari-iphone-home-screen")
        self.assertEqual(safari["scenarios"], {"warm-launch": "pass", "logout-cleanup": "pending"})
        self.assertEqual(home_screen["scenarios"], {"warm-launch": "pending", "logout-cleanup": "pending"})
        self.assertEqual(summary, {
            "profiles_imported": 1,
            "results_imported": 1,
            "pass": 1,
            "fail": 0,
            "pending": 3,
            "total": 4,
        })
        self.assertTrue(payload["redaction_reviewed"])

    def test_progress_rejects_remote_or_wrong_candidate_smoke(self) -> None:
        smoke = {
            "schema": "maverick.pwa-physical-browser-smoke.v1",
            "captured_at": NOW.isoformat(),
            "environment": "remote-webdriver",
            "redaction_reviewed": True,
            "release_id": "release-2026-09-05",
            "profile": "safari-macos-browser",
            "os_version": "physical-os-version",
            "browser_version": "physical-browser-version",
            "scenarios": {},
        }

        with self.assertRaisesRegex(ValueError, "not physical-device"):
            merge_smoke_progress(POLICY, "release-2026-09-05", [smoke])
        smoke["environment"] = "physical-device"
        smoke["release_id"] = "another-release"
        with self.assertRaisesRegex(ValueError, "does not match"):
            merge_smoke_progress(POLICY, "release-2026-09-05", [smoke])

    def test_accepts_current_complete_physical_matrix(self) -> None:
        self.assertEqual(
            validate_evidence(
                valid_evidence(),
                POLICY,
                expected_release_id="release-2026-09-05",
                now=NOW,
            ),
            [],
        )

    def test_release_waiver_accepts_pending_but_never_changes_strict_verification(self) -> None:
        payload = valid_evidence()
        payload["runs"][0]["scenarios"]["warm-launch"] = "pending"
        waiver = valid_waiver(passed=3, pending=1)

        self.assertTrue(any("non-passing scenarios" in error for error in validate_evidence(
            payload,
            POLICY,
            expected_release_id="release-2026-09-05",
            now=NOW,
        )))
        self.assertEqual(
            validate_release_evidence(
                payload,
                POLICY,
                expected_release_id="release-2026-09-05",
                waiver=waiver,
                now=NOW,
            ),
            [],
        )

    def test_release_waiver_rejects_failures_and_count_mismatches(self) -> None:
        payload = valid_evidence()
        payload["runs"][0]["scenarios"]["warm-launch"] = "fail"
        waiver = valid_waiver(passed=3, pending=1)

        errors = validate_release_evidence(
            payload,
            POLICY,
            expected_release_id="release-2026-09-05",
            waiver=waiver,
            now=NOW,
        )

        self.assertTrue(any("cannot cover failed" in error for error in errors))
        self.assertTrue(any("observed_results" in error for error in errors))

    def test_release_waiver_is_exact_candidate_bound_and_short_lived(self) -> None:
        payload = valid_evidence()
        payload["runs"][0]["scenarios"]["warm-launch"] = "pending"
        waiver = valid_waiver(passed=3, pending=1)
        waiver["release_id"] = "another-release"
        waiver["expires_at"] = (NOW + timedelta(days=8)).isoformat()

        errors = validate_release_evidence(
            payload,
            POLICY,
            expected_release_id="release-2026-09-05",
            waiver=waiver,
            now=NOW,
        )

        self.assertTrue(any("waiver release_id" in error for error in errors))
        self.assertTrue(any("maximum lifetime" in error for error in errors))

    def test_template_adds_profile_specific_degradation_scenarios(self) -> None:
        policy = deepcopy(POLICY)
        policy["device_regression"]["profile_scenarios"] = {
            "safari-macos-browser": ["private-storage-degradation"]
        }

        payload = evidence_template(policy, "release-2026-09-05")

        safari = next(run for run in payload["runs"] if run["profile"] == "safari-macos-browser")
        home_screen = next(run for run in payload["runs"] if run["profile"] == "safari-iphone-home-screen")
        self.assertIn("private-storage-degradation", safari["scenarios"])
        self.assertNotIn("private-storage-degradation", home_screen["scenarios"])

    def test_rejects_stale_or_incomplete_evidence(self) -> None:
        payload = valid_evidence()
        payload["captured_at"] = (NOW - timedelta(days=91)).isoformat()
        payload["runs"][0]["scenarios"]["warm-launch"] = "fail"

        errors = validate_evidence(
            payload,
            POLICY,
            expected_release_id="release-2026-09-05",
            now=NOW,
        )

        self.assertTrue(any("older than 90 days" in error for error in errors))
        self.assertTrue(any("non-passing scenarios" in error for error in errors))

    def test_rejects_identifiers_and_urls_from_evidence(self) -> None:
        payload = deepcopy(valid_evidence())
        payload["runs"][0]["device_serial"] = "serial-value"
        payload["runs"][0]["debug"] = "https://private.example/path"

        errors = validate_evidence(
            payload,
            POLICY,
            expected_release_id="release-2026-09-05",
            now=NOW,
        )

        self.assertTrue(any("sensitive diagnostic field" in error for error in errors))
        self.assertTrue(any("unexpected evidence field" in error for error in errors))
        self.assertTrue(any("URLs are prohibited" in error for error in errors))

    def test_rejects_evidence_for_a_different_release_candidate(self) -> None:
        payload = valid_evidence()
        payload["release_id"] = "unrelated-old-build"

        errors = validate_evidence(
            payload,
            POLICY,
            expected_release_id="release-2026-09-05",
            now=NOW,
        )

        self.assertTrue(any("does not match the expected release candidate" in error for error in errors))

    def test_rejects_an_invalid_expected_release_identity(self) -> None:
        errors = validate_evidence(
            valid_evidence(),
            POLICY,
            expected_release_id="",
            now=NOW,
        )

        self.assertTrue(any("expected_release_id" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
