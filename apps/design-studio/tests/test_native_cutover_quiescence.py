"""Managed sidecar quiescence proofs for the one-time native cutover."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from cutover_native_opendesign import (  # noqa: E402
    main as cutover_main,
    _require_managed_writer_ready,
    _stop_managed_writer,
)
from native_cutover_quiescence import (  # noqa: E402
    quiesce_native_host,
    reject_if_native_host_quiesced,
    release_native_host,
)
from native_cutover_state import (  # noqa: E402
    BACKUP_DIRECTORY,
    INVENTORY_CATEGORIES,
    MARKER_FILE,
    NativeDataCutoverError,
    read_marker,
)


class NativeCutoverQuiescenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="native-cutover-quiescence-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _prepare_activation(self, identifier: str) -> None:
        digest = "a" * 64
        marker = {
            "schema_version": "1",
            "kind": "design-studio-official-native-cutover",
            "cutover_id": identifier,
            "phase": "prepared",
            "created_at": "2026-08-30T00:00:00Z",
            "updated_at": "2026-08-30T00:00:00Z",
            "backup_directory": f"{BACKUP_DIRECTORY}/official-native-{identifier}",
            "source_generation": "generation-test",
            "source_tree_sha256": digest,
            "native_tree_sha256": digest,
            "public_inventory_sha256": digest,
            "inventory_categories": {
                category: {"count": 0, "sha256": digest}
                for category in INVENTORY_CATEGORIES
            },
            "legacy_read_only_files": [],
            "legacy_source_read_only": True,
            "legacy_writer_enabled": False,
            "native_writer_started": False,
            "native_ready": False,
            "rollback_to_legacy_allowed": True,
            "writer": "official-native-opendesign",
            "semantic_content_copied_to_maverick_state": False,
        }
        (self.root / MARKER_FILE).write_text(
            json.dumps(marker),
            encoding="utf-8",
        )
        quiesce_native_host(self.root, cutover_id=identifier)

    def _assert_activation_remains_reversible(self) -> None:
        persisted = read_marker(self.root / MARKER_FILE)
        self.assertEqual(persisted["phase"], "prepared")
        self.assertFalse(persisted["native_writer_started"])
        self.assertTrue(persisted["rollback_to_legacy_allowed"])
        self.assertTrue((self.root / "native-cutover-quiesce.json").is_file())

    def test_operator_requires_confirmation_and_quiesces_before_managed_stop(self) -> None:
        with self.assertRaisesRegex(NativeDataCutoverError, "confirmation"):
            _stop_managed_writer(
                self.root,
                cutover_id="native_stop_test",
                confirmed=False,
            )
        with patch(
            "cutover_native_opendesign._request_sidecar_control",
            return_value={
                "workspace_id": "default",
                "app_id": "design-studio",
                "data_root": str(self.root.resolve()),
                "ready": False,
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
        ) as control:
            _stop_managed_writer(
                self.root,
                cutover_id="native_stop_test",
                confirmed=True,
            )
        control.assert_called_once_with("stop", workspace_id="default")
        self.assertTrue((self.root / "native-cutover-quiesce.json").is_file())

    def test_zero_or_wrong_workspace_stop_evidence_is_rejected(self) -> None:
        invalid = (
            {
                "workspace_id": "wrong",
                "app_id": "design-studio",
                "data_root": str(self.root.resolve()),
                "ready": False,
                "browser_sessions_revoked": True,
                "declared_service_count": 1,
                "verified_stopped_service_count": 1,
                "services": [
                    {
                        "sidecar_id": "opendesign",
                        "live_instance_id": None,
                        "state": "stopped",
                    }
                ],
            },
            {
                "workspace_id": "default",
                "app_id": "design-studio",
                "data_root": str(self.root.resolve()),
                "ready": False,
                "browser_sessions_revoked": True,
                "declared_service_count": 0,
                "verified_stopped_service_count": 0,
                "services": [],
            },
        )
        for response in invalid:
            with self.subTest(response=response), patch(
                "cutover_native_opendesign._request_sidecar_control",
                return_value=response,
            ):
                with self.assertRaisesRegex(NativeDataCutoverError, "did not confirm"):
                    _stop_managed_writer(
                        self.root,
                        cutover_id="native_invalid_stop_test",
                        confirmed=True,
                    )

    def test_activation_rejects_readiness_from_an_unrelated_workspace(self) -> None:
        response = {
            "workspace_id": "unrelated-workspace",
            "app_id": "design-studio",
            "data_root": str(self.root.resolve()),
            "ready": True,
            "declared_service_count": 1,
            "verified_ready_service_count": 1,
            "services": [
                {
                    "sidecar_id": "opendesign",
                    "live_instance_id": "unrelated-instance",
                    "state": "ready",
                }
            ],
        }
        with patch(
            "cutover_native_opendesign._request_sidecar_control",
            return_value=response,
        ):
            with self.assertRaisesRegex(NativeDataCutoverError, "did not confirm"):
                _require_managed_writer_ready(
                    self.root,
                    workspace_id="default",
                )

    def test_activate_rejects_wrong_binding_before_irreversible_activation(self) -> None:
        identifier = "native_binding_preflight"
        self._prepare_activation(identifier)
        unrelated_root = self.root / "unrelated-binding"
        unrelated_root.mkdir()
        response = {
            "workspace_id": "unrelated-workspace",
            "app_id": "design-studio",
            "data_root": str(unrelated_root.resolve()),
            "declared_service_count": 1,
            "verified_stopped_service_count": 1,
            "services": [
                {
                    "sidecar_id": "opendesign",
                    "live_instance_id": None,
                    "state": "stopped",
                }
            ],
        }

        with (
            patch(
                "cutover_native_opendesign._request_sidecar_control",
                return_value=response,
            ) as control,
            patch.object(
                sys,
                "argv",
                [
                    "cutover_native_opendesign.py",
                    "activate",
                    "--data-root",
                    str(self.root),
                    "--cutover-id",
                    identifier,
                    "--workspace-id",
                    "unrelated-workspace",
                    "--confirm-writers-stopped",
                ],
            ),
            self.assertRaisesRegex(NativeDataCutoverError, "binding"),
        ):
            cutover_main()

        self._assert_activation_remains_reversible()
        control.assert_called_once_with(
            "status",
            workspace_id="unrelated-workspace",
        )

    def test_activate_requires_non_quarantined_binding_before_irreversible_activation(
        self,
    ) -> None:
        identifier = "native_quarantine_preflight"
        self._prepare_activation(identifier)
        verified_status = {
            "workspace_id": "default",
            "app_id": "design-studio",
            "data_root": str(self.root.resolve()),
            "declared_service_count": 1,
            "verified_stopped_service_count": 1,
            "services": [
                {
                    "sidecar_id": "opendesign",
                    "live_instance_id": None,
                    "state": "stopped",
                }
            ],
        }
        for quarantine_state in ("active", "missing"):
            with self.subTest(quarantine_state=quarantine_state):
                response = dict(verified_status)
                if quarantine_state == "active":
                    response["quarantined"] = True
                with (
                    patch(
                        "cutover_native_opendesign._request_sidecar_control",
                        return_value=response,
                    ) as control,
                    patch.object(
                        sys,
                        "argv",
                        [
                            "cutover_native_opendesign.py",
                            "activate",
                            "--data-root",
                            str(self.root),
                            "--cutover-id",
                            identifier,
                            "--workspace-id",
                            "default",
                            "--confirm-writers-stopped",
                        ],
                    ),
                    self.assertRaisesRegex(NativeDataCutoverError, "quarantined"),
                ):
                    cutover_main()

                self._assert_activation_remains_reversible()
                control.assert_called_once_with("status", workspace_id="default")

    def test_quiescence_blocks_relaunch_until_the_matching_cutover_releases_it(self) -> None:
        quiesce_native_host(self.root, cutover_id="native_quiesce_test")

        with self.assertRaisesRegex(NativeDataCutoverError, "host is quiesced"):
            reject_if_native_host_quiesced(self.root)
        with self.assertRaisesRegex(NativeDataCutoverError, "identity mismatch"):
            release_native_host(self.root, cutover_id="native_wrong_test")

        release_native_host(self.root, cutover_id="native_quiesce_test")
        reject_if_native_host_quiesced(self.root)


if __name__ == "__main__":
    unittest.main()
