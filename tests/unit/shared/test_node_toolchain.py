"""Protected isolated Node is admitted without trusting arbitrary repo trees."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.apps.errors import AppHostingError
from core.apps.sidecar_execution import _trusted_node_runtime
from core.shared.node_toolchain import is_protected_installation_node


@unittest.skipUnless(os.geteuid() == 0, 'installation toolchain trust requires root ownership')
class InstallationNodeTrustTests(unittest.TestCase):
    def setUp(self):
        cache = Path(__file__).resolve().parents[3] / '.cache/tmp'
        cache.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.toolchain = self.root / '.toolchains/node-v24.11.0-linux-x64'
        self.node = self.toolchain / 'bin/node'
        self.node.parent.mkdir(parents=True)
        self.node.write_text('#!/bin/sh\nexit 0\n')
        self.node.chmod(0o755)
        self.root_patch = patch('core.shared.node_toolchain.installation_node_toolchain_root', return_value=self.toolchain)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def test_protected_declared_distribution_is_admitted_and_symlink_alias_resolves(self):
        alias = self.toolchain.parent / 'node'
        alias.symlink_to(self.toolchain.name)
        with patch('core.apps.sidecar_execution.shutil.which', return_value=str(alias / 'bin/node')):
            self.assertEqual(_trusted_node_runtime(), (self.node, self.toolchain))

    def test_other_repository_location_is_denied(self):
        with patch('core.apps.sidecar_execution.shutil.which', return_value=str(self.root / 'apps/node/bin/node')):
            with self.assertRaises(AppHostingError):
                _trusted_node_runtime()
        self.assertFalse(is_protected_installation_node(self.root / 'data/node/bin/node'))

    def test_writable_binary_or_ancestor_and_unowned_distribution_are_denied(self):
        for path in (self.node, self.node.parent, self.toolchain, self.toolchain.parent, self.root):
            mode = path.stat().st_mode & 0o777
            path.chmod(mode | 0o020)
            with self.subTest(path=path):
                self.assertFalse(is_protected_installation_node(self.node))
            path.chmod(mode)
        os.chown(self.toolchain, 12345, -1)
        self.assertFalse(is_protected_installation_node(self.node))
        os.chown(self.toolchain, 0, -1)

    def test_symlink_ancestor_is_denied(self):
        original = self.toolchain.parent
        moved = self.root / 'moved-toolchains'
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
        self.assertFalse(is_protected_installation_node(self.node))
