"""Durable and in-process sidecar quarantine proofs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.api.sidecar_proxy import HttpSidecarManager, resolve_authorized_sidecar
from core.apps.sidecar_quarantine import (
    SidecarQuarantineError,
    activate_sidecar_quarantine,
    active_sidecar_quarantine,
    release_sidecar_quarantine,
)
from core.apps.store import AppDocumentStore
from core.model_access.broker import ModelAccessBroker


class SidecarQuarantineTests(unittest.TestCase):
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
