"""Managed sidecar quiescence proofs for the one-time native cutover."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from cutover_native_opendesign import (  # noqa: E402
    _require_managed_writer_ready,
    _stop_managed_writer,
)
from native_cutover_quiescence import (  # noqa: E402
    quiesce_native_host,
    reject_if_native_host_quiesced,
    release_native_host,
)
from native_cutover_state import NativeDataCutoverError  # noqa: E402


class NativeCutoverQuiescenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="native-cutover-quiescence-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)

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
