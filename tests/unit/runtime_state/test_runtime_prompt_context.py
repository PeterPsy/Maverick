"""Workspace namespace and instruction parity without provider-specific policy."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from core.runtime.runtime_prompt_context import native_runtime_input, runtime_environment_context
from core.runtime.tool_errors import RuntimeToolError


class RuntimePromptContextTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        workspace = self.root / "workspace"
        (workspace / "project").mkdir(parents=True)
        self.session = SimpleNamespace(
            workspace_id="example", workspace_root=str(workspace),
            workdir=str(workspace / "project"), effective_mode="sandbox",
            system_prompt=None,
        )

    def test_native_and_full_access_api_use_the_same_real_paths(self):
        self.session.effective_mode = "full-access"
        native = runtime_environment_context(self.session, native=True)
        self.assertEqual(native, runtime_environment_context(self.session))
        self.assertEqual(native["workdir"], self.session.workdir)
        self.assertEqual(native["filesystem_scope"], "host")

    def test_sandbox_api_keeps_nested_workdir_without_host_paths(self):
        context = runtime_environment_context(self.session)
        self.assertEqual(context["workdir"], "workspace://example/project")
        self.assertEqual(context["workspace_root"], "workspace://example")
        self.assertEqual(context["filesystem_scope"], "workspace")
        self.assertNotIn(str(self.root), str(context))

    def test_root_to_leaf_instructions_are_complete_and_refresh_each_turn(self):
        workspace = Path(self.session.workspace_root)
        (workspace / "AGENTS.md").write_text("Root rules.\n")
        nested = workspace / "project" / "AGENTS.md"
        nested.write_text("Nested rules.\n" * 500)
        first = native_runtime_input(session=self.session, input_text="Inspect.")
        self.assertLess(first.index("Root rules."), first.index("Nested rules."))
        self.assertIn(nested.read_text(), first)
        nested.write_text("Changed rules.\n")
        second = native_runtime_input(session=self.session, input_text="Inspect.")
        self.assertIn("Changed rules.", second)
        self.assertNotIn("Nested rules.", second)

    def test_workspace_instruction_symlinks_do_not_escape_the_boundary(self):
        outside = self.root / "outside.md"
        outside.write_text("Must not be read.\n")
        (Path(self.session.workspace_root) / "AGENTS.md").symlink_to(outside)
        with self.assertRaises(RuntimeToolError):
            native_runtime_input(session=self.session, input_text="Inspect.")
