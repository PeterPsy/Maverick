"""Live-process Unix sidecar control-channel proofs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from core.api import sidecar_control
from core.apps.sidecar_restart import SidecarRestartError


class _Shutdown:
    stopping = False

    def is_shutting_down(self) -> bool:
        return self.stopping


class SidecarControlTests(unittest.TestCase):
    def test_stop_revokes_browser_authority_before_stopping_the_app(self) -> None:
        browser_sessions = Mock()
        state = SimpleNamespace(sidecar_browser_sessions=browser_sessions)
        request = {
            "schema_version": "1",
            "operation": "stop",
            "workspace_id": "default",
            "app_id": "design-studio",
        }
        with patch.object(sidecar_control, "stop_app_sidecars", return_value=1) as stop:
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
                "browser_sessions_revoked": True,
                "stopped_service_count": 1,
            },
        )

    def test_status_aggregates_the_live_manager_without_starting_a_sidecar(self) -> None:
        binding = SimpleNamespace(data_root="/data/design-studio")
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
        startup_status.assert_called_once_with(
            workspace_id="default",
            app_id="design-studio",
            sidecar_id="opendesign",
            data_root="/data/design-studio",
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
