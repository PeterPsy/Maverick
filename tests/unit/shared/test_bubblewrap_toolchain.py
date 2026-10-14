"""Only the exact protected installation Bubblewrap is added to OS trust."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.apps.errors import AppHostingError
from core.apps.sidecar_execution import _trusted_bubblewrap_binary


@unittest.skipUnless(os.geteuid() == 0, "Toolchain ownership checks require root")
class BubblewrapToolchainTests(unittest.TestCase):
    def test_declared_binary_and_real_ancestors_must_remain_protected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            binary = root / ".toolchains/bubblewrap-0.11.2-install/bin/bwrap"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\nexit 0\n"); binary.chmod(0o755)
            with patch("core.apps.sidecar_execution.__file__", str(root / "core/apps/sidecar_execution.py")), \
                 patch("core.apps.sidecar_execution.shutil.which", return_value=str(binary)):
                self.assertEqual(_trusted_bubblewrap_binary(), str(binary))
                for path in (binary, binary.parent, binary.parent.parent, root):
                    mode = path.stat().st_mode & 0o777; path.chmod(mode | 0o020)
                    with self.assertRaises(AppHostingError):
                        _trusted_bubblewrap_binary()
                    path.chmod(mode)
                os.chown(binary, 1234, -1)
                with self.assertRaises(AppHostingError):
                    _trusted_bubblewrap_binary()

    def test_arbitrary_protected_repository_binary_is_not_a_trust_root(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "bwrap"
            binary.write_text("#!/bin/sh\nexit 0\n"); binary.chmod(0o755)
            with patch("core.apps.sidecar_execution.shutil.which", return_value=str(binary)):
                with self.assertRaises(AppHostingError):
                    _trusted_bubblewrap_binary()
