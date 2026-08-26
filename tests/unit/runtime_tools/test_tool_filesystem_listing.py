"""Bounded workspace filesystem listing regressions."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.runtime.tool_catalog import RuntimeToolActorContext
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_errors import RuntimeToolError


class RuntimeFilesystemListingTest(unittest.TestCase):
    def test_listing_is_deterministic_content_free_bounded_and_symlink_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input.txt").write_text("safe", encoding="utf-8")
            (root / "nested").mkdir()
            (root / "nested" / "child.txt").write_text(
                "file content must not be returned",
                encoding="utf-8",
            )
            (root / "outside-link").symlink_to(root.parent)
            surface = next(
                item
                for item in build_core_runtime_tool_capabilities(
                    workspace_id="default",
                    workspace_root=root,
                )
                if item.definition.handle == "core-capability:filesystem.list"
            )
            context = RuntimeToolActorContext(
                workspace_id="default",
                actor_id="user-1",
                agent_id="chat",
                platform_role=None,
                workspace_role="member",
                session_id="session-list",
                execution_mode="sandbox",
            )

            first = surface.handler(
                {"path": ".", "max_depth": 2, "max_results": 10},
                context,
                None,
            )
            second = surface.handler(
                {"path": ".", "max_depth": 2, "max_results": 10},
                context,
                None,
            )

            self.assertEqual(first, second)
            self.assertEqual(
                [
                    {"path": item["path"], "type": item["type"]}
                    for item in first["entries"]
                ],
                [
                    {"path": "input.txt", "type": "file"},
                    {"path": "nested", "type": "directory"},
                    {"path": "outside-link", "type": "symlink"},
                    {"path": "nested/child.txt", "type": "file"},
                ],
            )
            self.assertNotIn("file content must not be returned", repr(first))

            truncated = surface.handler(
                {"path": ".", "max_depth": 2, "max_results": 2},
                context,
                None,
            )
            self.assertEqual(truncated["result_count"], 2)
            self.assertIs(truncated["truncated"], True)
            with self.assertRaises(RuntimeToolError):
                surface.handler({"path": "outside-link"}, context, None)
            with self.assertRaises(RuntimeToolError):
                surface.handler({"path": ".", "max_depth": 5}, context, None)

    def test_concurrent_directory_to_symlink_swap_cannot_escape_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            child = root / "child"
            child.mkdir()
            (child / "inside.txt").write_text("inside", encoding="utf-8")
            outside_path = Path(outside)
            (outside_path / "outside-secret-name.txt").write_text("secret", encoding="utf-8")
            context = RuntimeToolActorContext(
                workspace_id="default",
                actor_id="user-1",
                agent_id="chat",
                platform_role=None,
                workspace_role="member",
                session_id="session-race",
                execution_mode="sandbox",
            )
            swapped = False

            def swap_before_recursive_open(event: str, path: str) -> None:
                nonlocal swapped
                if (
                    event == "list_before_directory_open"
                    and path == "child"
                    and not swapped
                ):
                    swapped = True
                    child.rename(root / "original-child")
                    child.symlink_to(outside_path, target_is_directory=True)

            surface = next(
                item
                for item in build_core_runtime_tool_capabilities(
                    workspace_id="default",
                    workspace_root=root,
                    filesystem_race_hook=swap_before_recursive_open,
                )
                if item.definition.handle == "core-capability:filesystem.list"
            )

            with self.assertRaisesRegex(
                RuntimeToolError,
                "filesystem_snapshot_changed",
            ) as raised:
                surface.handler(
                    {"path": ".", "max_depth": 2, "max_results": 20},
                    context,
                    None,
                )

            self.assertTrue(swapped)
            self.assertNotIn("outside-secret-name.txt", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
