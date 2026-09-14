from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.runtime.runtime_paths import RuntimePathResolver
from core.runtime.tool_errors import RuntimeToolError


class RuntimePathResolverTest(unittest.TestCase):
    def test_full_access_normalizes_relative_uri_and_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            resolver = RuntimePathResolver(
                workspace_id="default",
                workspace_root=workspace,
                execution_mode="full-access",
            )

            self.assertEqual(resolver.resolve(".", allow_root=True).absolute, workspace)
            self.assertEqual(resolver.resolve("docs/readme.md").absolute, workspace / "docs/readme.md")
            self.assertEqual(
                resolver.resolve("workspace://default/docs/readme.md").absolute,
                workspace / "docs/readme.md",
            )
            self.assertEqual(
                resolver.resolve("/etc", allow_root=True).absolute,
                Path("/etc"),
            )

    def test_sandbox_uses_the_same_syntax_but_rejects_outside_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            resolver = RuntimePathResolver(
                workspace_id="default",
                workspace_root=workspace,
                execution_mode="sandbox",
            )

            self.assertEqual(
                resolver.resolve("workspace://default/.", allow_root=True).for_confined_filesystem(),
                ".",
            )
            with self.assertRaisesRegex(RuntimeToolError, "filesystem_path_outside_workspace"):
                resolver.resolve("/etc", allow_root=True)
            with self.assertRaisesRegex(RuntimeToolError, "filesystem_workspace_uri_invalid"):
                resolver.resolve("workspace://another/file.txt")


if __name__ == "__main__":
    unittest.main()
