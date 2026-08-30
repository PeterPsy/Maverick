"""Live-process Unix sidecar control-channel proofs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from core.api import sidecar_control, sidecar_quarantine_control
from core.apps.models import WorkspaceAppSidecarQuarantineRecord
from core.apps.sidecar_restart import SidecarRestartError


class _Shutdown:
    stopping = False

    def is_shutting_down(self) -> bool:
        return self.stopping


class SidecarControlTests(unittest.TestCase):
    def test_prewarm_returns_canonical_binding_and_live_instance_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "data/design-studio"
            data_root.mkdir(parents=True)
            binding = SimpleNamespace(
                workspace_id="default",
                app_id="design-studio",
                data_root=str(data_root),
                status="enabled",
            )
            app_store = Mock()
            app_store.get_workspace_app_binding.return_value = binding
            state = SimpleNamespace(
                app_store=app_store,
                repository_root=Path(temporary),
            )
            prewarm_result = {
                "ready": True,
                "service_count": 1,
                "instance_count": 1,
                "verified_ready_service_count": 1,
                "services": [
                    {
                        "sidecar_id": "opendesign",
                        "live_instance_id": "instance-ready",
                        "state": "ready",
                    }
                ],
            }

            with patch.object(
                sidecar_control,
                "prewarm_workspace_app_sidecars",
                return_value=prewarm_result,
            ):
                result = sidecar_control._dispatch(
                    {
                        "schema_version": "1",
                        "operation": "prewarm",
                        "workspace_id": "default",
                        "app_id": "design-studio",
                    },
                    state=state,
                    shutdown_controller=None,
                )

        self.assertEqual(result["workspace_id"], "default")
        self.assertEqual(result["app_id"], "design-studio")
        self.assertEqual(result["data_root"], str(data_root.resolve()))
        self.assertEqual(result["declared_service_count"], 1)
        self.assertEqual(result["verified_ready_service_count"], 1)
        self.assertEqual(result["services"][0]["live_instance_id"], "instance-ready")

    def test_stop_revokes_browser_authority_before_stopping_the_app(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "data/design-studio"
            data_root.mkdir(parents=True)
            browser_sessions = Mock()
            binding = SimpleNamespace(data_root=str(data_root), status="enabled")
            app_store = Mock()
            app_store.get_workspace_app_binding.return_value = binding
            state = SimpleNamespace(
                sidecar_browser_sessions=browser_sessions,
                app_store=app_store,
                repository_root=Path(temporary),
            )
            request = {
                "schema_version": "1",
                "operation": "stop",
                "workspace_id": "default",
                "app_id": "design-studio",
            }
            sidecar = SimpleNamespace(service_id="opendesign")
            parsed = SimpleNamespace(
                contract=SimpleNamespace(
                    services=SimpleNamespace(http_sidecars=[sidecar]),
                )
            )
            with (
                patch.object(
                    sidecar_control,
                    "resolve_workspace_app_surface",
                    return_value=(Path(temporary) / "app", parsed),
                ),
                patch.object(
                    sidecar_control,
                    "app_sidecar_current_instance_id",
                    side_effect=["instance-1", None],
                ),
                patch.object(
                    sidecar_control,
                    "app_sidecar_startup_status",
                    return_value={"state": "stopped"},
                ),
                patch.object(sidecar_control, "stop_app_sidecars", return_value=1) as stop,
            ):
                result = sidecar_control._dispatch(
                    request,
                    state=state,
                    shutdown_controller=None,
                )

        browser_sessions.revoke_app.assert_called_once_with(
            workspace_id="default",
            app_id="design-studio",
        )
        stop.assert_called_once_with(workspace_id="default", app_id="design-studio")
        self.assertEqual(
            result,
            {
                "ready": False,
                "workspace_id": "default",
                "app_id": "design-studio",
                "data_root": str(data_root.resolve()),
                "browser_sessions_revoked": True,
                "declared_service_count": 1,
                "stopped_service_count": 1,
                "verified_stopped_service_count": 1,
                "services": [
                    {
                        "sidecar_id": "opendesign",
                        "previous_instance_id": "instance-1",
                        "live_instance_id": None,
                        "state": "stopped",
                    }
                ],
            },
        )

    def test_stop_rejects_a_missing_workspace_binding_before_claiming_success(self) -> None:
        app_store = Mock()
        app_store.get_workspace_app_binding.side_effect = RuntimeError("missing")
        state = SimpleNamespace(
            sidecar_browser_sessions=Mock(),
            app_store=app_store,
            repository_root=Path("/repo"),
        )
        with self.assertRaises(sidecar_control.SidecarControlError) as raised:
            sidecar_control._dispatch(
                {
                    "schema_version": "1",
                    "operation": "stop",
                    "workspace_id": "missing",
                    "app_id": "design-studio",
                },
                state=state,
                shutdown_controller=None,
            )
        self.assertEqual(raised.exception.phase, "sidecar_stop_resolve")
        state.sidecar_browser_sessions.revoke_app.assert_not_called()

    def test_status_aggregates_the_live_manager_without_starting_a_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "data/design-studio"
            data_root.mkdir(parents=True)
            binding = SimpleNamespace(data_root=str(data_root), status="enabled")
            app_store = Mock()
            app_store.get_workspace_app_binding.return_value = binding
            state = SimpleNamespace(app_store=app_store, repository_root=Path("/repo"))
            sidecar = SimpleNamespace(service_id="opendesign")
            parsed = SimpleNamespace(
                contract=SimpleNamespace(
                    services=SimpleNamespace(http_sidecars=[sidecar]),
                ),
            )
            with (
                patch.object(
                    sidecar_control,
                    "resolve_workspace_app_surface",
                    return_value=(Path("/app"), parsed),
                ),
                patch.object(
                    sidecar_control,
                    "app_sidecar_startup_status",
                    return_value={
                        "state": "ready",
                        "phase": "health_recheck",
                        "instance_id": "instance-1",
                    },
                ) as startup_status,
                patch.object(
                    sidecar_control,
                    "app_sidecar_current_instance_id",
                    return_value="instance-1",
                ),
            ):
                result = sidecar_control._dispatch(
                    {
                        "schema_version": "1",
                        "operation": "status",
                        "workspace_id": "default",
                        "app_id": "design-studio",
                    },
                    state=state,
                    shutdown_controller=None,
                )

        self.assertEqual(result["services"][0]["state"], "ready")
        self.assertEqual(result["data_root"], str(data_root.resolve()))
        self.assertEqual(result["declared_service_count"], 1)
        self.assertEqual(result["verified_stopped_service_count"], 0)
        self.assertEqual(result["services"][0]["live_instance_id"], "instance-1")
        startup_status.assert_called_once_with(
            workspace_id="default",
            app_id="design-studio",
            sidecar_id="opendesign",
            data_root=str(data_root),
        )

    def test_quarantine_persists_before_revoking_every_live_capability(self) -> None:
        calls: list[str] = []
        browser_sessions = Mock()
        browser_sessions.revoke_app.side_effect = lambda **_kwargs: calls.append("browser")
        app_store = Mock()
        state = SimpleNamespace(
            repository_root=Path("/repo"),
            app_store=app_store,
            sidecar_browser_sessions=browser_sessions,
        )
        quarantine = WorkspaceAppSidecarQuarantineRecord(
            quarantine_id="sidecar-quarantine-unit",
            workspace_id="default",
            app_id="design-studio",
            reason="sidecar_recovery_required",
            active=True,
            created_at="2026-08-29T00:00:00Z",
            updated_at="2026-08-29T00:00:00Z",
        )

        def persist(*_args, **_kwargs):
            calls.append("persist")
            return quarantine

        with (
            patch.object(
                sidecar_quarantine_control,
                "activate_sidecar_quarantine",
                side_effect=persist,
            ),
            patch.object(
                sidecar_quarantine_control,
                "revoke_model_access_leases",
                side_effect=lambda *_args, **_kwargs: calls.append("model") or 1,
            ),
            patch.object(
                sidecar_quarantine_control,
                "quarantine_app_sidecars",
                side_effect=lambda **_kwargs: calls.append("proxy") or {
                    "proxy_revoked": True,
                    "writer_stop_confirmed": False,
                    "affected_service_count": 1,
                },
            ),
        ):
            result = sidecar_control._dispatch(
                {
                    "schema_version": "1",
                    "operation": "quarantine",
                    "workspace_id": "default",
                    "app_id": "design-studio",
                },
                state=state,
                shutdown_controller=None,
            )

        self.assertEqual(calls, ["persist", "browser", "model", "proxy"])
        self.assertTrue(result["quarantined"])
        self.assertTrue(result["persistent"])
        self.assertTrue(result["proxy_revoked"])
        self.assertTrue(result["browser_sessions_revoked"])
        self.assertTrue(result["model_access_revoked"])
        self.assertFalse(result["writer_stop_confirmed"])

    def test_quarantine_attempts_every_revocation_after_independent_failures(self) -> None:
        calls: list[str] = []
        browser_sessions = Mock()
        browser_sessions.revoke_app.side_effect = RuntimeError("browser failure")
        state = SimpleNamespace(
            repository_root=Path("/repo"),
            app_store=Mock(),
            sidecar_browser_sessions=browser_sessions,
        )
        quarantine = WorkspaceAppSidecarQuarantineRecord(
            quarantine_id="sidecar-quarantine-errors",
            workspace_id="default",
            app_id="design-studio",
            reason="sidecar_recovery_required",
            active=True,
            created_at="2026-08-29T00:00:00Z",
            updated_at="2026-08-29T00:00:00Z",
        )

        with (
            patch.object(
                sidecar_quarantine_control,
                "activate_sidecar_quarantine",
                return_value=quarantine,
            ),
            patch.object(
                sidecar_quarantine_control,
                "revoke_model_access_leases",
                side_effect=RuntimeError("model failure"),
            ) as revoke_models,
            patch.object(
                sidecar_quarantine_control,
                "quarantine_app_sidecars",
                side_effect=lambda **_kwargs: calls.append("proxy") or {
                    "proxy_revoked": True,
                    "writer_stop_confirmed": False,
                    "affected_service_count": 1,
                },
            ) as revoke_proxy,
        ):
            result = sidecar_quarantine_control.quarantine_workspace_app_sidecars(
                state,
                workspace_id="default",
                app_id="design-studio",
            )

        self.assertEqual(calls, ["proxy"])
        revoke_models.assert_called_once()
        revoke_proxy.assert_called_once()
        self.assertTrue(result["persistent"])
        self.assertFalse(result["browser_sessions_revoked"])
        self.assertFalse(result["model_access_revoked"])
        self.assertTrue(result["proxy_revoked"])
        self.assertEqual(
            result["revocation_errors"],
            ["browser_sessions", "model_access"],
        )

    def test_owner_authenticated_client_reaches_the_live_server_thread(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sidecar-control-") as temporary:
            repository = Path(temporary)
            shutdown = _Shutdown()
            state = SimpleNamespace(repository_root=repository)
            expected = {"ready": True, "service_count": 1, "instance_count": 1}
            with patch.object(sidecar_control, "_dispatch", return_value=expected) as dispatch:
                thread = sidecar_control.start_sidecar_control_server(
                    state,
                    shutdown_controller=shutdown,
                )
                self.assertIsNotNone(thread)
                socket_path = sidecar_control.sidecar_control_socket_path(repository)
                deadline = time.monotonic() + 2
                while not socket_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(socket_path.exists())

                result = sidecar_control.request_sidecar_control(
                    repository,
                    operation="prewarm",
                    workspace_id="default",
                    app_id="design-studio",
                    timeout_seconds=2,
                )
                self.assertEqual(result, expected)
                request = dispatch.call_args.args[0]
                self.assertEqual(request["operation"], "prewarm")
                self.assertEqual(request["workspace_id"], "default")
                self.assertEqual(request["app_id"], "design-studio")

                shutdown.stopping = True
                assert thread is not None
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())

    def test_typed_restart_failure_preserves_code_and_phase(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sidecar-control-") as temporary:
            repository = Path(temporary)
            shutdown = _Shutdown()
            state = SimpleNamespace(repository_root=repository)
            failure = SidecarRestartError(
                "runtime_binding_invalid",
                "sidecar_contract_resolve",
                "redacted",
            )
            with patch.object(sidecar_control, "_dispatch", side_effect=failure):
                thread = sidecar_control.start_sidecar_control_server(
                    state,
                    shutdown_controller=shutdown,
                )
                socket_path = sidecar_control.sidecar_control_socket_path(repository)
                deadline = time.monotonic() + 2
                while not socket_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)

                with self.assertRaises(sidecar_control.SidecarControlError) as raised:
                    sidecar_control.request_sidecar_control(
                        repository,
                        operation="prewarm",
                        workspace_id="default",
                        app_id="design-studio",
                        timeout_seconds=2,
                    )
                self.assertEqual(raised.exception.code, "runtime_binding_invalid")
                self.assertEqual(raised.exception.phase, "sidecar_contract_resolve")

                shutdown.stopping = True
                assert thread is not None
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
