"""Tests for the private single-file sidecar diagnostics capability."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from core.apps.contracts import build_http_sidecar_diagnostics, build_http_sidecar_spec
from core.apps.sidecar_execution import _prepare_sidecar_diagnostics_file
from core.apps.sidecar_execution import _replace_sidecar_diagnostics_file
from core.apps.errors import AppHostingError


class SidecarDiagnosticsFileTests(unittest.TestCase):
    def test_repairs_mode_on_a_file_owned_by_the_active_account(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "native-host-status.json"
            path.write_text("stale", encoding="utf-8")
            path.chmod(0o666)
            inode = path.stat().st_ino

            prepared = _prepare_sidecar_diagnostics_file(
                workspace=root,
                binding_data=root,
                sidecar=_sidecar(),
            )

            self.assertEqual(prepared, path.resolve())
            self.assertEqual(path.stat().st_ino, inode)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.read_bytes(), b"")

    def test_atomically_hands_off_a_stale_shared_group_inode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o2770)
            path = root / "native-host-status.json"
            path.write_text("untrusted stale payload", encoding="utf-8")
            path.chmod(0o660)
            previous_inode = path.stat().st_ino
            actual_uid = os.geteuid()

            with patch(
                "core.apps.sidecar_execution.os.geteuid",
                side_effect=(actual_uid + 1, actual_uid, actual_uid),
            ):
                prepared = _prepare_sidecar_diagnostics_file(
                    workspace=root,
                    binding_data=root,
                    sidecar=_sidecar(),
                )

            self.assertEqual(prepared, path.resolve())
            self.assertNotEqual(path.stat().st_ino, previous_inode)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.read_bytes(), b"")

    def test_rejects_a_path_changed_during_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "native-host-status.json"
            path.write_bytes(b"stale")
            expected = path.stat()
            path.unlink()
            path.write_bytes(b"replacement")

            with self.assertRaisesRegex(AppHostingError, "changed during handoff"):
                _replace_sidecar_diagnostics_file(path, expected=expected)


def _sidecar():
    return build_http_sidecar_spec(
        service_id="probe",
        command=["python3", "server.py"],
        diagnostics=build_http_sidecar_diagnostics(
            status_file="native-host-status.json"
        ),
    )


if __name__ == "__main__":
    unittest.main()
