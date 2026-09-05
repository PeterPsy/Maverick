from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from scripts.pwa_device_regression import evidence_template, validate_evidence


NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
POLICY = {
    "device_regression": {
        "release_candidate_binding": "exact_release_id",
        "max_evidence_age_days": 90,
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


class PwaDeviceRegressionTests(unittest.TestCase):
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
