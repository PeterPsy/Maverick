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

from cutover_native_opendesign import _stop_managed_writer  # noqa: E402
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
            return_value={"ready": False, "stopped_service_count": 1},
        ) as control:
            _stop_managed_writer(
                self.root,
                cutover_id="native_stop_test",
                confirmed=True,
            )
        control.assert_called_once_with("stop", workspace_id="default")
        self.assertTrue((self.root / "native-cutover-quiesce.json").is_file())

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
