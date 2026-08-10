"""Validate the redaction-safe WP10 product evidence and global gate map."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = APP_ROOT.parents[1]
SERVICE_ROOT = APP_ROOT / "service"
PRODUCT_EVIDENCE = SERVICE_ROOT / "opendesign_product_acceptance_0_16_1.json"
HOSTED_EVIDENCE = SERVICE_ROOT / "opendesign_hosted_acceptance_0_16_1.json"
GLOBAL_ACCEPTANCE = SERVICE_ROOT / "opendesign_production_acceptance_0_16_1.json"
CORRELATION_KEYS = {
    "workspace_id",
    "local_app_id",
    "sidecar_id",
    "od_project_id",
    "od_run_id",
    "runtime_session_id",
    "turn_id",
    "request_id",
    "correlation_id",
}
SCENARIO_IDS = {
    "login_open",
    "create_project_ui",
    "storage_import",
    "runtime_start",
    "incremental_sse",
    "generated_preview",
    "cancel_long_run",
    "storage_export",
    "restart_reload",
    "deep_link",
    "workspace_isolation",
    "forbidden_routes",
    "secret_boundary",
    "upgrade_rollback",
}


class OpenDesignProductionAcceptanceTest(unittest.TestCase):
    def test_product_evidence_covers_real_pinned_path_and_all_scenarios(self) -> None:
        evidence = _read_json(PRODUCT_EVIDENCE)

        self.assertEqual(evidence["gate"], "WP10")
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(evidence["opendesign"]["version"], "0.16.1")
        self.assertEqual(evidence["opendesign"]["oci_reference"], "ghcr.io/nexu-io/od:0.16.1")
        self.assertEqual(
            evidence["opendesign"]["artifact_sha256"],
            "b91ce140e6fc8302dc4d4b83dac197d4735533c0f141a44100ff1eeff8904e70",
        )
        product_path = evidence["product_path"]
        for key in (
            "official_oci_daemon",
            "real_chromium",
            "real_maverick_core",
            "real_sidecar_broker",
            "real_storage_app",
            "external_runtime_protocol_fixture",
        ):
            self.assertIs(product_path[key], True, key)
        for key in ("local_next_build", "docker_socket", "remote_iframe"):
            self.assertIs(product_path[key], False, key)

        scenarios = evidence["scenarios"]
        self.assertEqual({item["id"] for item in scenarios}, SCENARIO_IDS)
        self.assertEqual(len(scenarios), 14)
        for scenario in scenarios:
            self.assertEqual(scenario["status"], "passed", scenario["id"])
            correlation = scenario["correlation"]
            self.assertEqual(set(correlation), CORRELATION_KEYS, scenario["id"])
            self.assertTrue(all(isinstance(correlation[key], str) and correlation[key] for key in CORRELATION_KEYS))
        isolation = next(item for item in scenarios if item["id"] == "workspace_isolation")
        self.assertEqual(isolation["correlation"]["workspace_id"], "workspace-b")
        self.assertTrue(isolation["proof"]["distinct_origins"])
        canceled = next(item for item in scenarios if item["id"] == "cancel_long_run")
        self.assertNotEqual(canceled["correlation"]["od_run_id"], evidence["canonical_entity"]["od_run_id"])
        self.assertTrue(canceled["proof"]["repeated_cancel_safe"])

    def test_product_evidence_is_redaction_safe(self) -> None:
        evidence = _read_json(PRODUCT_EVIDENCE)

        self.assertEqual(
            evidence["redaction"],
            {
                "full_prompt_recorded": False,
                "credential_value_recorded": False,
                "environment_recorded": False,
                "host_path_recorded": False,
            },
        )
        serialized = json.dumps(evidence, sort_keys=True)
        self.assertNotIn("maverick_session=", serialized)
        self.assertNotIn("OD_API_TOKEN", serialized)
        self.assertNotIn("Authorization: Bearer", serialized)
        self.assertNotIn("/tmp/", serialized)
        secret_proof = next(item for item in evidence["scenarios"] if item["id"] == "secret_boundary")["proof"]
        self.assertIs(secret_proof["maverick_cookie_forwarded"], False)
        self.assertIs(secret_proof["browser_bearer_forwarded"], False)
        self.assertGreaterEqual(secret_proof["one_shot_bootstrap_count"], 2)

    def test_hosted_evidence_covers_the_public_browser_path(self) -> None:
        evidence = _read_json(HOSTED_EVIDENCE)

        self.assertEqual(evidence["gate"], "hosted-origin")
        self.assertEqual(evidence["status"], "passed")
        self.assertTrue(evidence["platform_origin"].startswith("https://"))
        self.assertTrue(evidence["sidecar_origin"].startswith("https://sc-"))
        for key in (
            "ok",
            "ready",
            "persisted_project",
            "reload",
            "deep_link",
            "tls_verified_by_chromium",
            "bootstrap_cookie_secure",
            "x_frame_options_absent",
        ):
            self.assertIs(evidence[key], True, key)
        self.assertGreaterEqual(evidence["project_count"], 1)
        self.assertTrue(all(evidence["write_flow"].values()))
        serialized = json.dumps(evidence, sort_keys=True)
        for forbidden in ("maverick_session", "Authorization", "session_id", "/home/", "/tmp/"):
            self.assertNotIn(forbidden, serialized)

    def test_all_global_acceptance_criteria_have_stable_evidence(self) -> None:
        acceptance = _read_json(GLOBAL_ACCEPTANCE)

        self.assertEqual(acceptance["gate"], "WP10")
        self.assertEqual(acceptance["status"], "passed")
        criteria = acceptance["criteria"]
        self.assertEqual([item["criterion_id"] for item in criteria], [f"AG{index:02d}" for index in range(1, 25)])
        for criterion in criteria:
            self.assertEqual(criterion["status"], "passed", criterion["criterion_id"])
            self.assertTrue(criterion["requirement"].strip())
            self.assertTrue(criterion["evidence"], criterion["criterion_id"])
            for evidence in criterion["evidence"]:
                reference = str(evidence.get("ref") or "")
                self.assertFalse(Path(reference).is_absolute(), reference)
                self.assertTrue((REPOSITORY_ROOT / reference).is_file(), reference)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
