from __future__ import annotations

from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from aggregate_opendesign_release_evidence import aggregate  # noqa: E402
from benchmark_opendesign_change_to_live import BENCHMARK_FILE, _mutate_benchmark_patch  # noqa: E402
from opendesign_artifact import sha256_file  # noqa: E402


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
        benchmark = self._benchmark()

        result = aggregate(ui, migration, benchmark)

        self.assertEqual(result["scenario_count"], 14)
        self.assertTrue(result["rollback_gate_separate"])
        self.assertEqual(result["scenarios"][-1]["id"], "upgrade_rollback")
        self.assertEqual(result["opendesign"]["runtime_artifact_sha256"], "a" * 64)
        self.assertEqual(result["opendesign"]["web_overlay_sha256"], "b" * 64)
        self.assertFalse(result["change_to_live_benchmark"]["source_build_cache_hit"])
        self.assertTrue(result["change_to_live_benchmark"]["browser_remount_event_emitted"])

        ui["scenarios"][4]["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "13 passed scenarios"):
            aggregate(ui, migration, benchmark)

    def test_committed_change_to_live_benchmark_proves_a_real_uncached_patch_build(self) -> None:
        evidence = json.loads(
            (SERVICE_ROOT / "opendesign_change_to_live_benchmark_0_16_1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(evidence["schema_version"], "1")
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(evidence["change"]["file"], BENCHMARK_FILE)
        self.assertNotEqual(evidence["change"]["before_sha256"], evidence["change"]["after_sha256"])
        self.assertFalse(evidence["cache"]["source_build_cache_hit"])
        self.assertTrue(evidence["cache"]["workspace_build_cache_hit"])
        self.assertLessEqual(
            evidence["phases"]["change_to_live_seconds"],
            evidence["target_ceiling_seconds"],
        )
        self.assertNotEqual(
            evidence["selection"]["before"]["web_overlay_sha256"],
            evidence["selection"]["candidate"]["web_overlay_sha256"],
        )
        self.assertEqual(evidence["selection"]["restored"], evidence["selection"]["before"])
        self.assertTrue(evidence["activation"]["browser_remount_event_emitted"])

    def test_committed_release_aggregate_contains_all_passed_scenarios_and_both_digests(self) -> None:
        evidence = json.loads(
            (SERVICE_ROOT / "opendesign_release_acceptance_0_16_1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(evidence["schema_version"], "3")
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(evidence["scenario_count"], 14)
        self.assertTrue(evidence["rollback_gate_separate"])
        self.assertTrue(all(item["status"] == "passed" for item in evidence["scenarios"]))
        self.assertEqual(len(evidence["opendesign"]["runtime_artifact_sha256"]), 64)
        self.assertEqual(len(evidence["opendesign"]["web_overlay_sha256"]), 64)

        serialized = json.dumps(evidence, sort_keys=True)
        for forbidden in ("maverick_session=", "OD_API_TOKEN", "Authorization: Bearer", "/tmp/"):
            self.assertNotIn(forbidden, serialized)

    def test_aggregator_rejects_boolean_only_or_cached_benchmark_claims(self) -> None:
        benchmark = self._benchmark()
        benchmark["cache"]["source_build_cache_hit"] = True
        with self.assertRaisesRegex(ValueError, "did not compile"):
            from benchmark_opendesign_change_to_live import validate_change_to_live_benchmark

            validate_change_to_live_benchmark(
                benchmark,
                expected_runtime_digest="a" * 64,
                expected_baseline_web_digest="b" * 64,
                expected_patch_sha256=sha256_file(SERVICE_ROOT / "patches/0003-maverick-web-react.patch"),
            )

    def test_benchmark_mutates_real_patch_bytes_and_updates_the_post_image(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-benchmark-unit-") as temporary:
            root = Path(temporary)
            service = root / "service"
            shutil.copytree(SERVICE_ROOT / "patches", service / "patches")
            prepared = root / "prepared/apps/web/src"
            prepared.mkdir(parents=True)
            prepared_css = prepared / "index.css"
            prepared_css.write_text("  --mav-bg: #070708;\n", encoding="utf-8")

            change = _mutate_benchmark_patch(service, prepared_source=root / "prepared", nonce="unit-proof")
            series = json.loads((service / "patches/series.json").read_text(encoding="utf-8"))
            react = next(item for item in series["patches"] if item["component"] == "web-react")
            css = next(item for item in react["files"] if item["path"] == "apps/web/src/index.css")
            prepared_sha256 = sha256_file(prepared_css)

        self.assertNotEqual(change["before_sha256"], change["after_sha256"])
        self.assertEqual(react["sha256"], change["after_sha256"])
        self.assertEqual(css["post_sha256"], prepared_sha256)

    @staticmethod
    def _benchmark() -> dict:
        before = {
            "runtime_artifact_sha256": "a" * 64,
            "web_overlay_sha256": "b" * 64,
            "od_version": "0.16.1",
            "data_generation": "gen_test",
        }
        candidate = {**before, "web_overlay_sha256": "d" * 64}
        return {
            "schema_version": "1",
            "gate": "design-studio-opendesign-change-to-live",
            "status": "passed",
            "change": {
                "file": BENCHMARK_FILE,
                "before_sha256": sha256_file(SERVICE_ROOT / "patches/0003-maverick-web-react.patch"),
                "after_sha256": "e" * 64,
            },
            "cache_keys": {
                "baseline_source_build": "1" * 64,
                "candidate_source_build": "2" * 64,
            },
            "cache": {
                "duration_seconds": 80.0,
                "dependency_cache_hit": True,
                "source_build_cache_hit": False,
                "next_cache_hit": True,
                "install_skipped": True,
                "workspace_build_cache_hit": True,
            },
            "compiled_baseline": {
                "web_overlay_sha256": "f" * 64,
                "matches_active_selection": False,
            },
            "selection": {"before": before, "candidate": candidate, "restored": before},
            "phases": {
                "warmup_excluded_seconds": 1.0,
                "mutation_seconds": 0.1,
                "build_seconds": 70.0,
                "activation_restart_readiness_seconds": 9.0,
                "change_to_live_seconds": 80.0,
                "restoration_seconds": 8.0,
            },
            "activation": {
                "ready": True,
                "service_count": 1,
                "browser_remount_event_emitted": True,
            },
            "restoration": {"ready": True, "browser_remount_event_emitted": True},
            "target_ceiling_seconds": 180.0,
        }


if __name__ == "__main__":
    unittest.main()
