"""Private toolchains must be reachable without exposing their parent directories."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.model_access import cli_sandbox


class ModelAccessCliBinaryTests(unittest.TestCase):
    def test_private_binary_is_mounted_at_a_fixed_read_only_sandbox_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "private-toolchain/bin/codex"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"native-codex")
            executable.chmod(0o555)
            link = root / "codex-link"
            link.symlink_to(executable)
            bwrap = root / "bwrap"
            bwrap.write_text("#!/bin/sh\n")
            bwrap.chmod(0o555)
            workspace = root / "workspace"
            home = root / "technical-home"
            workspace.mkdir()
            home.mkdir()

            with patch.object(cli_sandbox.shutil, "which", return_value=str(bwrap)):
                command = cli_sandbox.codex_sandbox_command(
                    executable=link, data_root=workspace, inner_cwd="/workspace",
                    cli_home=home, argv=("--version",),
                )

            self.assertIn("/model-cli", command)
            source_index = command.index(str(executable.resolve()))
            self.assertEqual(
                command[source_index - 1:source_index + 2],
                ["--ro-bind", str(executable.resolve()), "/model-cli/codex"],
            )
            self.assertEqual(command[command.index("--") + 1:], ["/model-cli/codex", "--version"])
            self.assertNotIn(str(executable.parent), command)
            self.assertNotIn(str(root), command)
