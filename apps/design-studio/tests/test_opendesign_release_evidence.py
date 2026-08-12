from __future__ import annotations

from pathlib import Path
import json
import sys
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from aggregate_opendesign_release_evidence import aggregate  # noqa: E402


class ReleaseEvidenceTests(unittest.TestCase):
    def test_aggregator_requires_thirteen_ui_scenarios_plus_separate_rollback(self) -> None:
        ui = {
            "profile": "release",
            "status": "passed",
            "gate": "design-studio-e2e-release",
            "opendesign": {
                "runtime_artifact_sha256": "a" * 64,
                "web_overlay_sha256": "b" * 64,
            },
            "scenarios": [
                {"id": identifier, "status": "passed"}
                for identifier in (
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
                )
            ],
        }
        migration = {
            "ok": True,
            "workspace_data_migrated": False,
            "source_tree_sha256_before": "c" * 64,
            "source_tree_sha256_after": "c" * 64,
            "real_rollback": {"forward_generation_preserved": True},
        }

        result = aggregate(ui, migration)

        self.assertEqual(result["scenario_count"], 14)
        self.assertTrue(result["rollback_gate_separate"])
        self.assertEqual(result["scenarios"][-1]["id"], "upgrade_rollback")
        self.assertEqual(result["opendesign"]["runtime_artifact_sha256"], "a" * 64)
        self.assertEqual(result["opendesign"]["web_overlay_sha256"], "b" * 64)

        ui["scenarios"][4]["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "13 passed scenarios"):
            aggregate(ui, migration)

    def test_incremental_release_acceptance_records_final_selection_and_split_gate(self) -> None:
        evidence = json.loads(
            (SERVICE_ROOT / "opendesign_incremental_release_acceptance_0_16_1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(evidence["schema_version"], "2")
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(len(evidence["selection"]["runtime_artifact_sha256"]), 64)
        self.assertEqual(len(evidence["selection"]["web_overlay_sha256"]), 64)
        self.assertEqual(evidence["release_gate"]["scenario_count"], 14)
        self.assertEqual(evidence["release_gate"]["ui_scenario_count"], 13)
        self.assertTrue(evidence["release_gate"]["migration_rollback_separate"])
        self.assertTrue(evidence["incremental_performance"]["warm_overlay_target_met"])
        self.assertTrue(evidence["incremental_performance"]["wrapper_target_met"])
        self.assertTrue(evidence["incremental_performance"]["backend_target_met"])

    def test_committed_release_aggregate_contains_all_passed_scenarios_and_both_digests(self) -> None:
        evidence = json.loads(
            (SERVICE_ROOT / "opendesign_release_acceptance_0_16_1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(evidence["schema_version"], "2")
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(evidence["scenario_count"], 14)
        self.assertTrue(evidence["rollback_gate_separate"])
        self.assertTrue(all(item["status"] == "passed" for item in evidence["scenarios"]))
        self.assertEqual(len(evidence["opendesign"]["runtime_artifact_sha256"]), 64)
        self.assertEqual(len(evidence["opendesign"]["web_overlay_sha256"]), 64)

        serialized = json.dumps(evidence, sort_keys=True)
        for forbidden in ("maverick_session=", "OD_API_TOKEN", "Authorization: Bearer", "/tmp/"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
