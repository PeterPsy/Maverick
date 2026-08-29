"""Durable and in-process sidecar quarantine proofs."""

from __future__ import annotations

from pathlib import Path
from threading import BoundedSemaphore
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.api.sidecar_proxy import (
    HttpSidecarManager,
    RunningSidecar,
    resolve_authorized_sidecar,
)
from core.apps.sidecar_execution import ConfinedSidecarLaunch
from core.apps.sidecar_quarantine import (
    SidecarQuarantineError,
    activate_sidecar_quarantine,
    active_sidecar_quarantine,
    release_sidecar_quarantine,
)
from core.apps.store import AppDocumentStore
from core.model_access.broker import ModelAccessBroker


def _confined_launch(
    relay_directory: Path,
    relay_socket: Path,
    *,
    model_access_release=None,
) -> ConfinedSidecarLaunch:
    return ConfinedSidecarLaunch(
        command=[],
        env={},
        relay_directory=relay_directory,
        relay_socket=relay_socket,
        relay_capability="capability",
        secret_fd=-1,
        passwd_fd=-1,
        model_access_release=model_access_release,
    )


class SidecarQuarantineTests(unittest.TestCase):
    def test_capability_revocation_unlinks_relay_even_when_model_release_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            relay_directory = Path(temporary) / "relay"
            relay_directory.mkdir()
            relay_socket = relay_directory / "r.sock"
            relay_socket.touch()
            launch = _confined_launch(
                relay_directory,
                relay_socket,
                model_access_release=Mock(side_effect=RuntimeError("release failed")),
            )

            result = launch.revoke_capabilities()

            self.assertFalse(result.model_access_revoked)
            self.assertTrue(result.relay_revoked)
            self.assertFalse(relay_socket.exists())

    def test_proxy_revocation_evidence_is_false_while_relay_path_remains(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            relay_directory = Path(temporary) / "relay"
            relay_directory.mkdir()
            relay_socket = relay_directory / "r.sock"
            relay_socket.mkdir()
            launch = _confined_launch(relay_directory, relay_socket)
            process = Mock()
            process.poll.return_value = 0
            running = RunningSidecar(
                process=process,
                host="127.0.0.1",
                port=1,
                token="technical",
                instance_id="instance",
                confined_launch=launch,
                request_slots=BoundedSemaphore(1),
            )
            manager = HttpSidecarManager()
            manager._running[("default", "design-studio", "opendesign", "/data")] = running

            result = manager.quarantine_app(
                workspace_id="default",
                app_id="design-studio",
            )

            self.assertFalse(result["proxy_revoked"])
            self.assertTrue(result["writer_stop_confirmed"])
            self.assertTrue(relay_socket.exists())

    def test_quarantine_survives_a_new_core_store_instance_until_explicit_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = ControlStoreSettings.from_environment(
                repository_root=Path(temporary),
                environment={},
            )
            first = AppDocumentStore(build_control_plane_collections(settings).apps)
            persisted = activate_sidecar_quarantine(
                first,
                workspace_id="default",
                app_id="design-studio",
                reason="sidecar_recovery_required",
            )

            restarted = AppDocumentStore(build_control_plane_collections(settings).apps)
            active = active_sidecar_quarantine(
                restarted,
                workspace_id="default",
                app_id="design-studio",
            )

            self.assertIsNotNone(active)
            assert active is not None
            self.assertEqual(active.quarantine_id, persisted.quarantine_id)
            target, error = resolve_authorized_sidecar(
                SimpleNamespace(app_store=restarted),
                workspace_id="default",
                app_id="design-studio",
                sidecar_id="opendesign",
                user=object(),
                start_path=Path(temporary),
            )
            self.assertIsNone(target)
            self.assertIsNotNone(error)
            assert error is not None
            self.assertEqual(error.payload, {"error": "sidecar_quarantined"})
            released = release_sidecar_quarantine(
                restarted,
                workspace_id="default",
                app_id="design-studio",
            )
            self.assertIsNotNone(released)
            self.assertIsNone(
                active_sidecar_quarantine(
                    restarted,
                    workspace_id="default",
                    app_id="design-studio",
                )
            )

    def test_in_process_quarantine_blocks_a_racing_sidecar_start(self) -> None:
        manager = HttpSidecarManager()
        result = manager.quarantine_app(
            workspace_id="default",
            app_id="design-studio",
        )

        self.assertTrue(result["proxy_revoked"])
        self.assertTrue(result["writer_stop_confirmed"])
        with self.assertRaises(SidecarQuarantineError):
            manager.ensure_running(
                workspace_id="default",
                app_id="design-studio",
                source_root=Path("/unused"),
                data_root="/unused",
                sidecar=SimpleNamespace(service_id="opendesign"),
                start_path=Path("/unused"),
                shutdown_controller=None,
            )

    def test_persisted_quarantine_revokes_existing_and_new_model_leases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = ControlStoreSettings.from_environment(
                repository_root=root,
                environment={},
            )
            store = AppDocumentStore(build_control_plane_collections(settings).apps)
            data_root = root / "data/design-studio"
            data_root.mkdir(parents=True)
            broker = ModelAccessBroker(
                SimpleNamespace(app_store=store, repository_root=root),
                socket_path=root / "model-access/broker.sock",
            )
            broker.start()
            self.addCleanup(broker.stop)
            lease = broker.issue(
                workspace_id="default",
                app_id="design-studio",
                sidecar_id="opendesign",
                data_root=data_root,
                api=True,
                cli=("codex",),
            )
            activate_sidecar_quarantine(
                store,
                workspace_id="default",
                app_id="design-studio",
                reason="sidecar_recovery_required",
            )

            with self.assertRaisesRegex(PermissionError, "quarantined"):
                broker.authorize(f"Bearer {lease.token}")
            with self.assertRaisesRegex(PermissionError, "invalid"):
                broker.authorize(f"Bearer {lease.token}")
            with self.assertRaises(SidecarQuarantineError):
                broker.issue(
                    workspace_id="default",
                    app_id="design-studio",
                    sidecar_id="opendesign",
                    data_root=data_root,
                    api=True,
                    cli=("codex",),
                )


if __name__ == "__main__":
    unittest.main()
