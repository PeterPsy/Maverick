"""Transactional completion contract for governed OpenDesign artifact repair."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
sys.path.insert(0, str(SERVICE_ROOT))

import opendesign_artifact_operations as operations  # noqa: E402


RUNTIME_DIGEST = "a" * 64
WEB_DIGEST = "b" * 64


class OpenDesignRepairCompletionTests(unittest.TestCase):
    def test_lifecycle_hook_returns_materialized_without_reentering_core_prewarm(self) -> None:
        hook_path = ROOT / "apps/design-studio/hooks/artifact_repair.py"
        spec = importlib.util.spec_from_file_location(
            "design_studio_artifact_repair_completion_test",
            hook_path,
        )
        assert spec is not None and spec.loader is not None
        hook = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = hook
        spec.loader.exec_module(hook)
        data_root = ROOT / "workspaces/default/data/design-studio"
        emitted: list[dict[str, object]] = []
        with (
            patch.object(
                hook,
                "read_entrypoint_payload",
                return_value=SimpleNamespace(
                    data_root=str(data_root),
                    workspace_id="default",
                ),
            ),
            patch.object(
                hook,
                "run_artifact_operation",
                return_value={"status": "materialized"},
            ) as repair,
            patch.object(hook, "write_repair_state") as state,
            patch.object(hook, "emit_json", side_effect=emitted.append),
        ):
            hook.main()

        repair.assert_called_once_with(
            "repair",
            data_root=data_root,
            workspace_id="default",
            auto=True,
            complete_repair=False,
        )
        self.assertEqual(
            state.call_args_list,
            [call(data_root, state="repairing"), call(data_root, state="idle")],
        )
        self.assertEqual(
            emitted,
            [{"ok": True, "repair": {"status": "materialized"}}],
        )

    def test_operator_repair_reports_ready_only_after_every_live_workspace_smokes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-governed-repair-") as temporary:
            repository = Path(temporary)
            roots = {
                "alpha": repository / "workspaces/alpha/data/design-studio",
                "bravo": repository / "workspaces/bravo/data/design-studio",
            }
            for root in roots.values():
                root.mkdir(parents=True)
            events: list[str] = []

            def control(_repository, *, operation, workspace_id, **_kwargs):
                events.append(f"control:{operation}:{workspace_id}")
                if operation == "stop-all-workspaces":
                    return {"affected_workspace_ids": ["bravo"]}
                return {"restart": workspace_id}

            def materialize(operation, **kwargs):
                events.append(f"artifact:{operation}")
                self.assertFalse(kwargs["complete_repair"])
                return {
                    "schema_version": "1",
                    "operation": "repair",
                    "status": "materialized",
                    "duration_ms": 12.5,
                    "store_generation": "store-generation",
                }

            def smoke(_repository, *, workspace_id, **_kwargs):
                events.append(f"smoke:{workspace_id}")
                return {
                    "workspace_id": workspace_id,
                    "fresh_health_recheck": True,
                    "browser_entrypoint_smoke": True,
                    "transactional_readiness": True,
                    "artifact_fast_recheck": True,
                }

            with (
                patch.object(
                    operations,
                    "discover_design_studio_workspace_data_roots",
                    return_value=roots,
                ),
                patch.object(operations, "request_sidecar_control", side_effect=control),
                patch.object(operations, "run_artifact_operation", side_effect=materialize) as repair,
                patch.object(
                    operations,
                    "governed_repair_runtime_smoke",
                    side_effect=smoke,
                ),
                patch.object(operations, "write_repair_state") as state,
                patch.object(operations, "_invalidate_runtime_readiness"),
            ):
                result = operations._run_governed_operator_repair(
                    repository,
                    data_root=roots["alpha"],
                    workspace_id="alpha",
                    audit_workers=3,
                )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["materialization_duration_ms"], 12.5)
        self.assertEqual(
            result["runtime_validation"]["restarted_workspace_ids"],
            ["alpha", "bravo"],
        )
        self.assertTrue(result["runtime_validation"]["governed_smoke_complete"])
        self.assertEqual(
            events,
            [
                "control:stop-all-workspaces:alpha",
                "artifact:repair",
                "control:restart:alpha",
                "smoke:alpha",
                "control:restart:bravo",
                "smoke:bravo",
            ],
        )
        repair.assert_called_once()
        self.assertEqual(
            state.call_args_list,
            [
                call(roots["alpha"], state="repairing"),
                call(roots["bravo"], state="repairing"),
                call(roots["alpha"], state="idle"),
                call(roots["bravo"], state="idle"),
            ],
        )

    def test_failed_smoke_stops_every_consumer_and_never_reports_ready(self) -> None:
        class SmokeFailure(RuntimeError):
            code = "activation_incomplete"
            phase = "repair_smoke_launcher"

        with tempfile.TemporaryDirectory(prefix="od-governed-repair-failure-") as temporary:
            repository = Path(temporary)
            data_root = repository / "workspaces/default/data/design-studio"
            data_root.mkdir(parents=True)
            controls: list[str] = []

            def control(_repository, *, operation, **_kwargs):
                controls.append(operation)
                if operation == "stop-all-workspaces":
                    return {"affected_workspace_ids": []}
                return {"status": "ready"}

            with (
                patch.object(
                    operations,
                    "discover_design_studio_workspace_data_roots",
                    return_value={"default": data_root},
                ),
                patch.object(operations, "request_sidecar_control", side_effect=control),
                patch.object(
                    operations,
                    "run_artifact_operation",
                    return_value={
                        "schema_version": "1",
                        "operation": "repair",
                        "status": "materialized",
                        "duration_ms": 1.0,
                        "store_generation": "store-generation",
                    },
                ),
                patch.object(
                    operations,
                    "governed_repair_runtime_smoke",
                    side_effect=SmokeFailure("not ready"),
                ),
                patch.object(operations, "write_repair_state") as state,
                patch.object(operations, "_invalidate_runtime_readiness"),
                self.assertRaises(operations.ArtifactStoreError) as raised,
            ):
                operations._run_governed_operator_repair(
                    repository,
                    data_root=data_root,
                    workspace_id="default",
                    audit_workers=None,
                )

        self.assertEqual(raised.exception.code, "activation_incomplete")
        self.assertEqual(raised.exception.phase, "repair_smoke_launcher")
        self.assertEqual(
            controls,
            ["stop-all-workspaces", "restart", "stop-all-workspaces"],
        )
        self.assertEqual(state.call_args_list[0], call(data_root, state="repairing"))
        self.assertEqual(
            state.call_args_list[-1],
            call(
                data_root,
                state="failed",
                error_code="activation_incomplete",
                phase="repair_smoke_launcher",
            ),
        )

    def test_runtime_smoke_binds_fresh_health_browser_timing_marker_and_store(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-repair-runtime-smoke-") as temporary:
            repository = Path(temporary)
            data_root = repository / "workspaces/default/data/design-studio"
            generation = data_root / "opendesign"
            generation.mkdir(parents=True)
            launcher = {
                "schema_version": "3",
                "startup_id": "startup-identity",
                "phase": "browser_ready",
                "active": {
                    "runtime_artifact_sha256": RUNTIME_DIGEST,
                    "web_overlay_sha256": WEB_DIGEST,
                },
                "health": {
                    "artifact_available": True,
                    "artifact_verified": True,
                    "artifact_protected": True,
                    "sidecar_process_running": True,
                    "daemon_ready": True,
                    "activation_committed": True,
                    "browser_ready": True,
                },
                "timings_ms": {
                    "process_spawn_ms": 1.0,
                    "daemon_ready_ms": 2.0,
                    "activation_commit_ms": 3.0,
                    "browser_prewarm_ms": 4.0,
                },
            }
            marker = {
                "schema_version": "1",
                "startup_nonce": "startup-identity",
                "runtime_artifact_sha256": RUNTIME_DIGEST,
                "web_overlay_sha256": WEB_DIGEST,
            }
            (generation / "launcher-status.json").write_text(
                json.dumps(launcher), encoding="utf-8"
            )
            (generation / "maverick-ready.json").write_text(
                json.dumps(marker), encoding="utf-8"
            )
            restarted = {
                "status": "ready",
                "readiness": {
                    "ready": True,
                    "service_count": 1,
                    "services": [
                        {"service_id": "opendesign", "instance_id": "instance-123"}
                    ],
                },
            }
            controls = [
                {"ready": True, "service_count": 1, "instance_count": 1},
                {
                    "ready": True,
                    "service_count": 1,
                    "instance_count": 1,
                    "services": [
                        {
                            "service_id": "opendesign",
                            "instance_id": "instance-123",
                            "browser_entrypoint": True,
                            "response_bytes": 4096,
                        }
                    ],
                },
                {
                    "services": [
                        {
                            "sidecar_id": "opendesign",
                            "state": "ready",
                            "phase": "health_recheck",
                            "instance_id": "instance-123",
                        }
                    ]
                },
            ]
            artifact = {
                "schema_version": "1",
                "operation": "status",
                "status": "ready",
                "operational": True,
                "active": {
                    "runtime_artifact_sha256": RUNTIME_DIGEST,
                    "web_overlay_sha256": WEB_DIGEST,
                },
            }
            with (
                patch.object(
                    operations,
                    "request_sidecar_control",
                    side_effect=controls,
                ) as control,
                patch.object(
                    operations,
                    "run_artifact_operation",
                    return_value=artifact,
                ) as status,
            ):
                result = operations.governed_repair_runtime_smoke(
                    repository,
                    data_root=data_root,
                    workspace_id="default",
                    restarted=restarted,
                )

        self.assertTrue(result["browser_entrypoint_smoke"])
        self.assertTrue(result["transactional_readiness"])
        self.assertEqual(result["sidecar_instance_id"], "instance-123")
        self.assertEqual(
            [item.kwargs["operation"] for item in control.call_args_list],
            ["prewarm", "smoke", "status"],
        )
        status.assert_called_once_with(
            "status",
            data_root=data_root,
            workspace_id="default",
            repository_root=repository,
        )

    def test_runtime_smoke_rejects_a_new_instance_during_health_recheck(self) -> None:
        restarted = {
            "status": "ready",
            "readiness": {
                "ready": True,
                "service_count": 1,
                "services": [
                    {"service_id": "opendesign", "instance_id": "instance-old"}
                ],
            },
        }
        controls = [
            {"ready": True, "service_count": 1, "instance_count": 1},
            {
                "ready": True,
                "service_count": 1,
                "instance_count": 1,
                "services": [
                    {
                        "service_id": "opendesign",
                        "instance_id": "instance-old",
                        "browser_entrypoint": True,
                        "response_bytes": 4096,
                    }
                ],
            },
            {
                "services": [
                    {
                        "sidecar_id": "opendesign",
                        "state": "ready",
                        "phase": "health_recheck",
                        "instance_id": "instance-new",
                    }
                ]
            },
        ]
        with (
            patch.object(operations, "request_sidecar_control", side_effect=controls),
            self.assertRaises(operations.ArtifactStoreError) as raised,
        ):
            operations.governed_repair_runtime_smoke(
                ROOT,
                data_root=ROOT / "workspaces/default/data/design-studio",
                workspace_id="default",
                restarted=restarted,
            )

        self.assertEqual(raised.exception.code, "activation_incomplete")
        self.assertEqual(raised.exception.phase, "repair_smoke_manager")


if __name__ == "__main__":
    unittest.main()
