from __future__ import annotations

import copy
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
            "performance": self._performance(),
            "failure_injection": self._failure_injection(),
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
        migration = self._migration()
        benchmark = self._benchmark()

        provenance = self._provenance()
        result = aggregate(
            ui,
            migration,
            benchmark,
            release_provenance=provenance,
            source_documents=self._documents(),
        )

        self.assertEqual(result["schema_version"], "6")
        self.assertEqual(result["scenario_count"], 14)
        self.assertTrue(result["rollback_gate_separate"])
        self.assertEqual(result["scenarios"][-1]["id"], "upgrade_rollback")
        self.assertEqual(result["opendesign"]["runtime_artifact_sha256"], "a" * 64)
        self.assertEqual(result["opendesign"]["web_overlay_sha256"], "b" * 64)
        self.assertFalse(result["change_to_live_benchmark"]["source_build_cache_hit"])
        self.assertTrue(result["change_to_live_benchmark"]["browser_remount_event_emitted"])

        ui["scenarios"][4]["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "canonical passed scenarios"):
            aggregate(
                ui,
                migration,
                benchmark,
                release_provenance=provenance,
                source_documents=self._documents(),
            )

    def test_aggregator_rejects_arbitrary_duplicate_scenarios_and_false_rollback_proofs(self) -> None:
        scenarios = [
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
        ]
        ui = {
            "profile": "release",
            "performance": self._performance(),
            "failure_injection": self._failure_injection(),
            "status": "passed",
            "opendesign": {
                "runtime_artifact_sha256": "a" * 64,
                "web_overlay_sha256": "b" * 64,
            },
            "scenarios": scenarios,
        }
        migration = self._migration()
        arbitrary = copy.deepcopy(ui)
        arbitrary["scenarios"] = [
            {"id": f"arbitrary_{index}", "status": "passed"} for index in range(13)
        ]
        with self.assertRaisesRegex(ValueError, "canonical passed scenarios"):
            aggregate(
                arbitrary,
                migration,
                self._benchmark(),
                release_provenance=self._provenance(),
                source_documents=self._documents(),
            )

        duplicated = copy.deepcopy(ui)
        duplicated["scenarios"][-1]["id"] = "workspace_isolation"
        with self.assertRaisesRegex(ValueError, "canonical passed scenarios"):
            aggregate(
                duplicated,
                migration,
                self._benchmark(),
                release_provenance=self._provenance(),
                source_documents=self._documents(),
            )

        rejected_source = copy.deepcopy(migration)
        rejected_source["forward_fixture_migration"]["source"]["tree_sha256_after"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "preservation proofs"):
            aggregate(
                ui,
                rejected_source,
                self._benchmark(),
                release_provenance=self._provenance(),
                source_documents=self._documents(),
            )
        rejected_rollback = copy.deepcopy(migration)
        rejected_rollback["rollback"]["forward_generation_preserved"] = False
        with self.assertRaisesRegex(ValueError, "preservation proofs"):
            aggregate(
                ui,
                rejected_rollback,
                self._benchmark(),
                release_provenance=self._provenance(),
                source_documents=self._documents(),
            )

    def test_aggregator_rejects_signed_overlay_inputs_from_an_older_patch_series(self) -> None:
        ui = {
            "profile": "release",
            "performance": self._performance(),
            "failure_injection": self._failure_injection(),
            "status": "passed",
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
        migration = self._migration()
        stale = self._provenance()
        stale["web_patch_sha256"]["web-build"] = "9" * 64

        with self.assertRaisesRegex(ValueError, "current patch series"):
            aggregate(
                ui,
                migration,
                self._benchmark(),
                release_provenance=stale,
                source_documents=self._documents(),
            )

    def test_aggregator_recomputes_samples_and_gates_the_complete_interface(self) -> None:
        ui = {
            "profile": "release",
            "performance": self._performance(),
            "failure_injection": self._failure_injection(),
            "status": "passed",
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
        arguments = {
            "migration": self._migration(),
            "benchmark": self._benchmark(),
            "release_provenance": self._provenance(),
            "source_documents": self._documents(),
        }

        tampered = copy.deepcopy(ui)
        tampered["performance"]["warm_browser_ticket"]["p95_ms"] = 1
        with self.assertRaisesRegex(ValueError, "does not match"):
            aggregate(tampered, **arguments)

        excluded_wrapper = copy.deepcopy(ui)
        excluded_wrapper["performance"]["warm_interface"]["full_wrapper_remount"]["p95_ms"] = 500
        with self.assertRaisesRegex(ValueError, "does not match|excludes"):
            aggregate(excluded_wrapper, **arguments)

        prewarm_completed_first = copy.deepcopy(ui)
        prewarm_completed_first["performance"]["samples"][0][
            "browser_request_during_prewarm"
        ] = False
        with self.assertRaisesRegex(ValueError, "browser/prewarm singleflight"):
            aggregate(prewarm_completed_first, **arguments)

        duplicate_start = copy.deepcopy(ui)
        duplicate_start["performance"]["samples"][0][
            "singleflight_sidecar_start_count"
        ] = 2
        with self.assertRaisesRegex(ValueError, "browser/prewarm singleflight"):
            aggregate(duplicate_start, **arguments)

        simulated_kill = copy.deepcopy(ui)
        simulated_kill["failure_injection"]["scenarios"][0]["real_process"] = False
        with self.assertRaisesRegex(ValueError, "process-kill recovery"):
            aggregate(simulated_kill, **arguments)

        leaked_partial_readiness = copy.deepcopy(ui)
        leaked_partial_readiness["failure_injection"]["scenarios"][3][
            "partial_readiness_exposed"
        ] = True
        with self.assertRaisesRegex(ValueError, "launch-phase failure"):
            aggregate(leaked_partial_readiness, **arguments)

        slow_cold_interface = copy.deepcopy(ui)
        for sample in slow_cold_interface["performance"]["samples"]:
            sample["browser_launch_response_to_usable_interface_ms"] = 4_100
            sample["shell_action_to_usable_interface_ms"] = 4_600
            sample["interface_phases_ms"]["usable_interface_ready_ms"] = 4_600
        slow_cold_interface["performance"]["cold_interface"].update(
            {"p50_ms": 4_100, "p95_ms": 4_100, "p99_ms": 4_100, "max_ms": 4_100}
        )
        slow_cold_interface["performance"]["concurrent_cold_interface"].update(
            {"p50_ms": 4_600, "p95_ms": 4_600, "p99_ms": 4_600, "max_ms": 4_600}
        )
        with self.assertRaisesRegex(ValueError, "SLOs did not pass"):
            aggregate(slow_cold_interface, **arguments)

        slow_warm_interface = copy.deepcopy(ui)
        slow_distribution = {
            "count": 30,
            "p50_ms": 10_000,
            "p95_ms": 10_000,
            "p99_ms": 10_000,
            "max_ms": 10_000,
            "samples_ms": [10_000.0] * 30,
        }
        slow_warm_interface["performance"]["warm_interface"].update(
            slow_distribution
        )
        slow_warm_interface["performance"]["warm_interface"][
            "full_wrapper_remount"
        ].update(slow_distribution)
        with self.assertRaisesRegex(ValueError, "SLOs did not pass"):
            aggregate(slow_warm_interface, **arguments)

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

    def test_committed_historical_release_aggregate_remains_redaction_safe(self) -> None:
        evidence = json.loads(
            (SERVICE_ROOT / "opendesign_release_acceptance_0_16_1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(evidence["schema_version"], "6")
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
    def _performance() -> dict:
        warm_samples = [100.0] * 27 + [200.0, 250.0, 260.0]
        distribution = {
            "count": 30,
            "p50_ms": 100,
            "p95_ms": 250,
            "p99_ms": 260,
            "max_ms": 260,
            "samples_ms": warm_samples,
        }
        cold = {"count": 10, "p50_ms": 1000, "p95_ms": 2000, "p99_ms": 2000, "max_ms": 2000}
        restart_samples = [
            {
                "iteration": index + 1,
                "cold_maverick_ready_ms": 1_000 if index < 9 else 2_000,
                "transactional_ready_after_core_start_ms": 1_200 if index < 9 else 2_200,
                "prewarm_after_core_health_ms": 1_000 if index < 9 else 2_000,
                "shell_action_to_usable_interface_ms": 1_000 if index < 9 else 1_500,
                "browser_launch_response_to_usable_interface_ms": 500 if index < 9 else 1_000,
                "browser_request_during_prewarm": True,
                "singleflight_sidecar_start_count": 1,
                "prewarm_browser_overlap_ms": 500,
                "prewarm_started_before_browser_request_ms": 100,
                "controlled_singleflight_overlap_delay_ms": 750,
                "interface_phases_ms": {
                    "launch_target_path": "/projects/od_project_1",
                    "launch_response_ms": 500,
                    "usable_interface_ready_ms": 1_000 if index < 9 else 1_500,
                },
                "resources": {"rss_kib": 100, "process_count": 2},
            }
            for index in range(10)
        ]
        warm_interface = {
            **distribution,
            "measurement_scope": "wrapper_navigation_to_usable_project_interface",
            "full_wrapper_remount": dict(distribution),
        }
        return {
            "schema_version": "3",
            "warm_browser_ticket": {
                **distribution,
                "priming_request_count": 5,
                "same_sidecar_instance": True,
            },
            "warm_interface": warm_interface,
            "cold_maverick_ready": {
                **cold,
                "measurement_scope": "sidecar_start_request_to_transactional_endpoint_ready",
            },
            "transactional_ready_after_core_start": {
                "count": 10,
                "p50_ms": 1_200,
                "p95_ms": 2_200,
                "p99_ms": 2_200,
                "max_ms": 2_200,
                "measurement_scope": "core_process_start_to_transactional_endpoint_ready",
            },
            "prewarm_after_core_health": {
                **cold,
                "measurement_scope": "core_health_to_transactional_endpoint_ready",
            },
            "cold_interface": {
                "count": 10,
                "p50_ms": 500,
                "p95_ms": 1000,
                "p99_ms": 1000,
                "max_ms": 1000,
                "measurement_scope": "browser_launch_response_to_usable_project_interface_after_concurrent_prewarm",
            },
            "concurrent_cold_interface": {
                "count": 10,
                "p50_ms": 1000,
                "p95_ms": 1500,
                "p99_ms": 1500,
                "max_ms": 1500,
                "measurement_scope": "shell_action_during_prewarm_to_usable_project_interface",
            },
            "cold_browser_prewarm_singleflight": {
                "sample_count": 10,
                "browser_request_during_prewarm": True,
                "max_sidecar_starts_per_restart": 1,
                "controlled_overlap_delay_ms": 750,
                "overlap": {
                    "count": 10,
                    "p50_ms": 500,
                    "p95_ms": 500,
                    "p99_ms": 500,
                    "max_ms": 500,
                },
            },
            "daemon_internal_ready": cold,
            "core_restart_count": 10,
            "resources": {
                "cpu_ticks_max": 10,
                "rss_kib_max": 100,
                "disk_read_bytes_max": 0,
                "process_count_max": 2,
            },
            "samples": restart_samples,
            "targets_met": True,
        }

    @staticmethod
    def _failure_injection() -> dict:
        common = {
            "signal": "SIGKILL",
            "real_process": True,
            "consumer_failed_closed": True,
            "instance_rotated": True,
            "transactional_readiness_recovered": True,
            "project_preserved": True,
        }
        return {
            "schema_version": "1",
            "status": "passed",
            "real_process_signals": True,
            "scenarios": [
                {"id": "launcher_sigkill", **common},
                {"id": "daemon_sigkill", **common},
                {
                    "id": "browser_prewarm_sigkill",
                    **common,
                    "phase": "browser_prewarm",
                    "prewarm_failed_closed": True,
                    "partial_readiness_exposed": False,
                    "stale_marker_rejected": False,
                    "startup_nonce_rotated": True,
                },
                {
                    "id": "readiness_commit_sigkill",
                    **common,
                    "phase": "readiness_commit",
                    "prewarm_failed_closed": True,
                    "partial_readiness_exposed": False,
                    "stale_marker_rejected": True,
                    "startup_nonce_rotated": True,
                },
            ],
            "all_consumers_failed_closed": True,
            "all_recoveries_transactionally_ready": True,
            "workspace_data_preserved": True,
        }

    @staticmethod
    def _documents() -> dict[str, dict[str, str]]:
        return {
            name: {
                "path": f"apps/design-studio/service/{name}.json",
                "sha256": character * 64,
            }
            for name, character in (("ui", "1"), ("migration", "2"), ("benchmark", "3"))
        }

    @staticmethod
    def _migration() -> dict:
        return {
            "schema_version": "2",
            "workspace_data_migrated": False,
            "forward_fixture_migration": {
                "api_import_read_back": "byte_identical",
                "source": {
                    "tree_sha256_before": "c" * 64,
                    "tree_sha256_after": "c" * 64,
                },
                "target": {"real_materialized_daemon": True},
            },
            "rollback": {
                "forward_generation_preserved": True,
                "distinct_0_10_1_to_0_16_1_triple_atomicity": "passed",
                "real_daemon_health_database_and_project_smoke": "passed",
            },
        }

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
                "protected_store_publish_seconds": 0.5,
                "activation_restart_readiness_seconds": 8.5,
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

    @staticmethod
    def _provenance() -> dict:
        return {
            "signed_overlay_manifest": True,
            "web_overlay_sha256": "b" * 64,
            "runtime_artifact_sha256": "a" * 64,
            "runtime_compatibility": ["a" * 64],
            "expected_runtime_artifact_sha256": "a" * 64,
            "upstream_commit": "1" * 40,
            "expected_upstream_commit": "1" * 40,
            "lockfile_sha256": "2" * 64,
            "expected_lockfile_sha256": "2" * 64,
            "web_patch_sha256": {"web-build": "3" * 64, "web-react": "4" * 64},
            "expected_web_patch_sha256": {"web-build": "3" * 64, "web-react": "4" * 64},
        }


if __name__ == "__main__":
    unittest.main()
