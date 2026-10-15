"""Workspace pinning must work through traversal-only private ancestors."""

import os
from pathlib import Path
import tempfile
import unittest

from core.runtime.confined_filesystem import ConfinedWorkspaceFilesystem


@unittest.skipUnless(hasattr(os, "O_PATH") and hasattr(os, "fork"), "Linux descriptors required")
class ConfinedRootTraversalTest(unittest.TestCase):
    def test_workspace_read_does_not_require_listing_private_ancestors(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            base.chmod(0o755)
            private = base / "private"
            workspace = private / "workspace"
            workspace.mkdir(parents=True)
            private.chmod(0o111)
            workspace.chmod(0o755)
            (workspace / "AGENTS.md").write_text("Workspace instructions")
            (workspace / "AGENTS.md").chmod(0o644)
            reader, writer = os.pipe()
            pid = os.fork()
            if pid == 0:
                os.close(reader)
                try:
                    if os.geteuid() == 0:
                        os.setgroups([])
                        os.setgid(65534)
                        os.setuid(65534)
                    try:
                        os.listdir(private)
                    except PermissionError:
                        pass
                    else:
                        raise AssertionError("private ancestor became listable")
                    filesystem = ConfinedWorkspaceFilesystem(
                        workspace_id="default", workspace_root=workspace,
                    )
                    try:
                        result = filesystem.read_text("AGENTS.md", max_bytes=128)
                        assert result.payload["content"] == "Workspace instructions"
                    finally:
                        filesystem.close()
                    outcome = b"ok"
                except BaseException as error:
                    outcome = repr(error).encode()
                os.write(writer, outcome)
                os.close(writer)
                os._exit(0)
            os.close(writer)
            try:
                outcome = os.read(reader, 4096)
                _, status = os.waitpid(pid, 0)
                self.assertEqual(status, 0)
                self.assertEqual(outcome, b"ok")
            finally:
                os.close(reader)
                private.chmod(0o755)
