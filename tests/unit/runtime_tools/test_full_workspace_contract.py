from __future__ import annotations

import base64
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import patch

from core.cli.command_registry import CliCommandRegistry
from core.cli.models import (
    CliCommandDefinition,
    CliInvocationPolicy,
)
from core.mcp.models import (
    McpInvocationPolicy,
    McpToolDefinition,
)
from core.mcp.tool_registry import McpToolRegistry
from core.runtime.hosted_tool_process_registry import HostedToolProcessRegistry
from core.runtime.process_control import runtime_processes_alive_for_session
from core.runtime.tool_catalog import RuntimeToolActorContext
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_discovery_capabilities import build_discovery_first_capabilities
from core.runtime.tool_errors import RuntimeToolError
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class FullWorkspaceContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = HostedAgenticHarness(self)
        self.workspace = self.harness.root / "workspaces" / "default"
        self.context = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="user-1",
            agent_id="agent-1",
            platform_role="admin",
            workspace_role="admin",
            session_id="session-hosted",
            execution_mode="full-access",
        )

    def test_filesystem_search_edit_patch_move_delete_and_scoped_instructions(self) -> None:
        nested = self.workspace / "project"
        nested.mkdir()
        (self.workspace / "AGENTS.md").write_text(
            "Root rules.\n",
            encoding="utf-8",
        )
        (nested / "AGENTS.md").write_text(
            "Project rules.\n",
            encoding="utf-8",
        )
        target = nested / "notes.txt"
        target.write_text("alpha needle\nbeta needle\n", encoding="utf-8")
        capabilities = self._capabilities()

        instructions = capabilities["core-capability:workspace.instructions"].handler(
            {"path": "project/notes.txt"},
            self.context,
            None,
        )
        self.assertEqual(
            [item["scope"] for item in instructions.payload["instructions"]],
            [".", "project"],
        )
        scope_digest = instructions.payload["scope_digest"]

        search = capabilities["core-capability:filesystem.search"].handler(
            {"path": ".", "query": "needle", "max_results": 1},
            self.context,
            None,
        )
        self.assertEqual(search.payload["total_result_count"], 2)
        second = capabilities["core-capability:filesystem.search"].handler(
            {"query": "ignored", "cursor": search.payload["next_cursor"]},
            self.context,
            None,
        )
        self.assertEqual(second.payload["matches"][0]["line"], 2)

        read = capabilities["core-capability:filesystem.read"].handler(
            {"path": "project/notes.txt"},
            self.context,
            None,
        )
        edit = capabilities["core-capability:filesystem.edit"].handler(
            {
                "path": "project/notes.txt",
                "old_text": "needle",
                "new_text": "match",
                "expected_occurrences": 2,
                "expected_resource_identity": read.payload["resource_identity"],
                "expected_resource_revision": read.payload["resource_revision"],
                "instruction_scope_digest": scope_digest,
            },
            self.context,
            None,
        )
        self.assertIn("+alpha match", edit.payload["diff"])

        patch = capabilities["core-capability:filesystem.patch"].handler(
            {
                "path": "project/notes.txt",
                "operations": [
                    {"old_text": "alpha", "new_text": "one"},
                    {"old_text": "beta", "new_text": "two"},
                ],
                "expected_resource_identity": edit.payload["resource_identity"],
                "expected_resource_revision": edit.payload["resource_revision"],
                "instruction_scope_digest": scope_digest,
            },
            self.context,
            None,
        )
        move = capabilities["core-capability:filesystem.move"].handler(
            {
                "source_path": "project/notes.txt",
                "destination_path": "project/renamed.txt",
                "expected_resource_identity": patch.payload["resource_identity"],
                "expected_resource_revision": patch.payload["resource_revision"],
                "source_instruction_scope_digest": scope_digest,
                "destination_instruction_scope_digest": scope_digest,
            },
            self.context,
            None,
        )
        self.assertFalse(target.exists())
        self.assertTrue((nested / "renamed.txt").exists())
        deleted = capabilities["core-capability:filesystem.delete"].handler(
            {
                "path": "project/renamed.txt",
                "expected_resource_identity": move.payload["resource_identity"],
                "expected_resource_revision": move.payload["resource_revision"],
                "instruction_scope_digest": scope_digest,
            },
            self.context,
            None,
        )
        self.assertTrue(deleted.payload["deleted"])
        self.assertFalse((nested / "renamed.txt").exists())

    def test_filesystem_read_exposes_binary_base64_projection(self) -> None:
        raw = b"%PDF-1.7\x00\xffbinary-evidence"
        (self.workspace / "evidence.pdf").write_bytes(raw)
        capabilities = self._capabilities()
        surface = capabilities["core-capability:filesystem.read"]

        result = surface.handler(
            {"path": "evidence.pdf", "encoding": "base64"},
            self.context,
            None,
        )

        self.assertEqual(
            base64.b64decode(str(result.payload["content_base64"])),
            raw,
        )
        self.assertEqual(result.payload["encoding"], "base64")
        self.assertEqual(
            surface.definition.input_schema["properties"]["encoding"]["enum"],
            ["utf-8", "base64"],
        )

    def test_every_direct_mutation_schema_requires_instruction_snapshot(self) -> None:
        capabilities = self._capabilities(processes=True)
        expected = {
            "core-capability:filesystem.write": {"instruction_scope_digest"},
            "core-capability:filesystem.edit": {"instruction_scope_digest"},
            "core-capability:filesystem.patch": {"instruction_scope_digest"},
            "core-capability:filesystem.move": {
                "source_instruction_scope_digest",
                "destination_instruction_scope_digest",
            },
            "core-capability:filesystem.delete": {"instruction_scope_digest"},
            "core-capability:shell.run": {"mutation_scopes"},
            "core-capability:process.start": {"mutation_scopes"},
        }

        for handle, required in expected.items():
            with self.subTest(handle=handle):
                schema_required = set(
                    capabilities[handle].definition.input_schema["required"]
                )
                self.assertTrue(required.issubset(schema_required))
                if "mutation_scopes" in required:
                    item_required = set(
                        capabilities[handle]
                        .definition.input_schema["properties"]["mutation_scopes"]
                        ["items"]["required"]
                    )
                    self.assertEqual(
                        item_required,
                        {"path", "instruction_scope_digest"},
                    )

    def test_mutation_rechecks_instruction_digest_before_effect(self) -> None:
        (self.workspace / "AGENTS.md").write_text("First.\n", encoding="utf-8")
        capabilities = self._capabilities()
        instructions = capabilities["core-capability:workspace.instructions"].handler(
            {"path": "created.txt"},
            self.context,
            None,
        )
        (self.workspace / "AGENTS.md").write_text("Changed.\n", encoding="utf-8")

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_instruction_scope_changed",
        ):
            capabilities["core-capability:filesystem.write"].handler(
                {
                    "path": "created.txt",
                    "content": "must not be written",
                    "create_only": True,
                    "instruction_scope_digest": instructions.payload["scope_digest"],
                },
                self.context,
                None,
            )
        self.assertFalse((self.workspace / "created.txt").exists())

    def test_shell_overlay_rolls_back_instruction_race_at_guarded_commit(self) -> None:
        agents = self.workspace / "AGENTS.md"
        agents.write_text("Initial.\n", encoding="utf-8")

        def race(stage, _path):
            if stage == "write_temporary_ready":
                agents.write_text("Raced.\n", encoding="utf-8")

        capabilities = self._capabilities(race_hook=race)
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )
        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_instruction_scope_changed",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "printf blocked > raced-shell.txt",
                    ],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": scope_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertFalse((self.workspace / "raced-shell.txt").exists())
        self.assertEqual(agents.read_text(encoding="utf-8"), "Raced.\n")

    def test_shell_overlay_rolls_back_every_file_after_late_batch_race(self) -> None:
        agents = self.workspace / "AGENTS.md"
        agents.write_text("Initial.\n", encoding="utf-8")
        existing = self.workspace / "0-existing.txt"
        existing.write_text("original", encoding="utf-8")

        def race(stage, path):
            if stage == "write_committed" and path == "b.txt":
                agents.write_text("Raced.\n", encoding="utf-8")

        capabilities = self._capabilities(race_hook=race)
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )
        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_instruction_scope_changed",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        (
                            "printf replacement > 0-existing.txt; "
                            "printf first > a.txt; printf second > b.txt"
                        ),
                    ],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": scope_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertFalse((self.workspace / "a.txt").exists())
        self.assertFalse((self.workspace / "b.txt").exists())
        self.assertEqual(existing.read_text(encoding="utf-8"), "original")
        self.assertEqual(agents.read_text(encoding="utf-8"), "Raced.\n")

    def test_shell_overlay_rolls_back_concurrent_later_file_metadata(self) -> None:
        (self.workspace / "AGENTS.md").write_text(
            "Metadata race rules.\n",
            encoding="utf-8",
        )
        first = self.workspace / "a.txt"
        second = self.workspace / "b.txt"
        first.write_text("first-old", encoding="utf-8")
        second.write_text("second-old", encoding="utf-8")
        try:
            os.setxattr(second, "user.maverick.race-probe", b"probe")
            os.removexattr(second, "user.maverick.race-probe")
        except OSError as error:
            self.skipTest(f"filesystem xattrs unavailable: {error}")

        def race(stage, path):
            if stage == "write_committed" and path == "a.txt":
                os.setxattr(second, "user.maverick.concurrent", b"retained")

        capabilities = self._capabilities(race_hook=race)
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )
        with self.assertRaisesRegex(
            RuntimeToolError,
            "filesystem_resource_changed",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "printf first-new > a.txt; printf second-new > b.txt",
                    ],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": scope_digest,
                        }
                    ],
                },
                self.context,
                None,
            )

        self.assertEqual(first.read_text(encoding="utf-8"), "first-old")
        self.assertEqual(second.read_text(encoding="utf-8"), "second-old")
        self.assertEqual(
            os.getxattr(second, "user.maverick.concurrent"),
            b"retained",
        )

    def test_shell_and_process_preserve_existing_file_metadata(self) -> None:
        agents = self.workspace / "AGENTS.md"
        agents.write_text("Metadata rules.\n", encoding="utf-8")
        shell_target = self.workspace / "shell-script.sh"
        process_target = self.workspace / "process-script.sh"
        expected_atimes: dict[Path, int] = {}
        for target in (shell_target, process_target):
            target.write_text("old\n", encoding="utf-8")
            target.chmod(0o755)
            try:
                os.setxattr(target, "user.maverick.fixture", b"retained")
            except OSError as error:
                self.skipTest(f"filesystem xattrs unavailable: {error}")
            old_atime_ns = time.time_ns() - 86_400_000_000_000
            os.utime(
                target,
                ns=(old_atime_ns, target.stat().st_mtime_ns),
            )
            expected_atimes[target] = old_atime_ns
        expected_owner = (shell_target.stat().st_uid, shell_target.stat().st_gid)
        capabilities = self._capabilities(processes=True)
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )

        shell = capabilities["core-capability:shell.run"].handler(
            {
                "argv": ["/bin/sh", "-c", "printf shell-new > shell-script.sh"],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": scope_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        self.assertTrue(shell["workspace_effects_committed"])

        started = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    "printf process-new > process-script.sh",
                ],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": scope_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        terminal = self._wait_for_process(
            capabilities,
            str(started.payload["process_id"]),
        )
        self.assertEqual(terminal.payload["status"], "exited")

        for target, expected_content in (
            (shell_target, "shell-new"),
            (process_target, "process-new"),
        ):
            with self.subTest(path=target.name):
                current = target.stat()
                self.assertEqual(target.read_text(encoding="utf-8"), expected_content)
                self.assertEqual(stat.S_IMODE(current.st_mode), 0o755)
                self.assertEqual((current.st_uid, current.st_gid), expected_owner)
                self.assertEqual(current.st_atime_ns, expected_atimes[target])
                self.assertEqual(
                    os.getxattr(target, "user.maverick.fixture"),
                    b"retained",
                )

    def test_shell_overlay_supports_read_modify_write_and_read_after_write(self) -> None:
        (self.workspace / "AGENTS.md").write_text(
            "Read-modify-write rules.\n",
            encoding="utf-8",
        )
        sed_target = self.workspace / "sed-existing.txt"
        read_target = self.workspace / "read-after-write.txt"
        sed_target.write_text("old value\n", encoding="utf-8")
        read_target.write_text("old\n", encoding="utf-8")
        old_atime_ns = time.time_ns() - 86_400_000_000_000
        os.utime(
            read_target,
            ns=(old_atime_ns, read_target.stat().st_mtime_ns),
        )
        capabilities = self._capabilities()
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )

        sed_result = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/bin/sed",
                    "-i",
                    "s/old/new/",
                    "sed-existing.txt",
                ],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": scope_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        self.assertTrue(sed_result["workspace_effects_committed"])
        self.assertEqual(sed_target.read_text(encoding="utf-8"), "new value\n")

        read_result = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    (
                        "printf new > read-after-write.txt; "
                        "cat read-after-write.txt >/dev/null"
                    ),
                ],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": scope_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        self.assertTrue(read_result["workspace_effects_committed"])
        committed = read_target.stat()
        self.assertGreater(committed.st_atime_ns, old_atime_ns)
        self.assertEqual(read_target.read_text(encoding="utf-8"), "new")

    def test_shell_overlay_materializes_file_times_and_rejects_root_atime(self) -> None:
        (self.workspace / "AGENTS.md").write_text(
            "Timestamp rules.\n",
            encoding="utf-8",
        )
        target = self.workspace / "timestamp.txt"
        target.write_text("old", encoding="utf-8")
        requested_mtime_ns = time.time_ns() + 1_500_000_000
        capabilities = self._capabilities()
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )

        result = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/usr/bin/python3",
                    "-c",
                    (
                        "import os; "
                        "p='timestamp.txt'; "
                        "open(p, 'w', encoding='utf-8').write('new'); "
                        "s=os.stat(p); "
                        f"os.utime(p, ns=(s.st_atime_ns, {requested_mtime_ns}))"
                    ),
                ],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": scope_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        self.assertTrue(result["workspace_effects_committed"])
        self.assertEqual(target.read_text(encoding="utf-8"), "new")
        self.assertEqual(target.stat().st_mtime_ns, requested_mtime_ns)

        requested_root_atime_ns = 946_684_800_000_000_000
        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_metadata_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/usr/bin/python3",
                        "-c",
                        (
                            "import os; s=os.stat('.'); "
                            f"os.utime('.', ns=({requested_root_atime_ns}, "
                            "s.st_mtime_ns))"
                        ),
                    ],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": scope_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertNotEqual(
            self.workspace.stat().st_atime_ns,
            requested_root_atime_ns,
        )

    def test_shell_overlay_rejects_new_and_existing_hardlinks(self) -> None:
        (self.workspace / "AGENTS.md").write_text(
            "Hardlink rules.\n",
            encoding="utf-8",
        )
        capabilities = self._capabilities()
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_hardlink_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "printf x > new-a; ln new-a new-b",
                    ],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": scope_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertFalse((self.workspace / "new-a").exists())
        self.assertFalse((self.workspace / "new-b").exists())

        existing_a = self.workspace / "existing-a"
        existing_b = self.workspace / "existing-b"
        existing_a.write_text("old", encoding="utf-8")
        os.link(existing_a, existing_b)
        original_inode = existing_a.stat().st_ino
        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_hardlink_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": ["/bin/sh", "-c", "printf new > existing-a"],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": scope_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertEqual(existing_a.read_text(encoding="utf-8"), "old")
        self.assertEqual(existing_b.read_text(encoding="utf-8"), "old")
        self.assertEqual(existing_a.stat().st_ino, original_inode)
        self.assertEqual(existing_b.stat().st_ino, original_inode)

    def test_process_status_is_mutating_and_batch_failure_is_not_retry_safe(self) -> None:
        agents = self.workspace / "AGENTS.md"
        agents.write_text("Initial.\n", encoding="utf-8")

        def race(stage, path):
            if stage == "write_committed" and path == "process-b.txt":
                agents.write_text("Raced.\n", encoding="utf-8")

        capabilities = self._capabilities(processes=True, race_hook=race)
        status_surface = capabilities["core-capability:process.status"]
        self.assertEqual(status_surface.definition.effect_class, "mutating")
        self.assertFalse(status_surface.definition.safe_to_retry)
        scope_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )
        started = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    (
                        "printf first > process-a.txt; "
                        "printf second > process-b.txt"
                    ),
                ],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": scope_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_instruction_scope_changed",
        ):
            self._wait_for_process(
                capabilities,
                str(started.payload["process_id"]),
            )
        record = self.harness.store.get_process(str(started.payload["process_id"]))
        self.assertEqual(record.status, "failed")
        self.assertFalse((self.workspace / "process-a.txt").exists())
        self.assertFalse((self.workspace / "process-b.txt").exists())

    def test_mutation_requires_digest_and_rolls_back_instruction_races(self) -> None:
        agents = self.workspace / "AGENTS.md"
        agents.write_text("Initial.\n", encoding="utf-8")
        capabilities = self._capabilities()
        with self.assertRaisesRegex(RuntimeToolError, "tool_arguments_invalid"):
            capabilities["core-capability:filesystem.write"].handler(
                {
                    "path": "without-digest.txt",
                    "content": "not written",
                    "create_only": True,
                },
                self.context,
                None,
            )
        self.assertFalse((self.workspace / "without-digest.txt").exists())

        for race_stage in ("write_temporary_ready", "write_committed"):
            with self.subTest(race_stage=race_stage):
                agents.write_text("Initial.\n", encoding="utf-8")

                def race(stage, _path):
                    if stage == race_stage:
                        agents.write_text("Raced.\n", encoding="utf-8")

                racing = self._capabilities(race_hook=race)
                scope_digest = self._scope_digest(racing, "raced.txt")
                with self.assertRaisesRegex(
                    RuntimeToolError,
                    "workspace_instruction_scope_changed",
                ):
                    racing["core-capability:filesystem.write"].handler(
                        {
                            "path": "raced.txt",
                            "content": "must roll back",
                            "create_only": True,
                            "instruction_scope_digest": scope_digest,
                        },
                        self.context,
                        None,
                    )
                self.assertFalse((self.workspace / "raced.txt").exists())
                self.assertEqual(agents.read_text(encoding="utf-8"), "Raced.\n")

        for operation, race_stage in (("move", "move_committed"), ("delete", "delete_committed")):
            with self.subTest(operation=operation):
                agents.write_text("Initial.\n", encoding="utf-8")
                source = self.workspace / f"{operation}-source.txt"
                source.write_text("preserve me", encoding="utf-8")

                def race(stage, _path):
                    if stage == race_stage:
                        agents.write_text("Raced.\n", encoding="utf-8")

                racing = self._capabilities(race_hook=race)
                observed = racing["core-capability:filesystem.read"].handler(
                    {"path": source.name},
                    self.context,
                    None,
                )
                scope_digest = self._scope_digest(racing, source.name)
                arguments = {
                    "expected_resource_identity": observed.payload[
                        "resource_identity"
                    ],
                    "expected_resource_revision": observed.payload[
                        "resource_revision"
                    ],
                }
                if operation == "move":
                    destination = self.workspace / "moved.txt"
                    arguments.update(
                        source_path=source.name,
                        destination_path=destination.name,
                        source_instruction_scope_digest=scope_digest,
                        destination_instruction_scope_digest=scope_digest,
                    )
                else:
                    destination = None
                    arguments.update(
                        path=source.name,
                        instruction_scope_digest=scope_digest,
                    )
                with self.assertRaisesRegex(
                    RuntimeToolError,
                    "workspace_instruction_scope_changed",
                ):
                    racing[f"core-capability:filesystem.{operation}"].handler(
                        arguments,
                        self.context,
                        None,
                    )
                self.assertTrue(source.exists())
                if destination is not None:
                    self.assertFalse(destination.exists())

    def test_intentional_agents_move_is_bound_to_both_original_scopes(self) -> None:
        agents = self.workspace / "AGENTS.md"
        destination_directory = self.workspace / "nested"
        destination_directory.mkdir()
        agents.write_text("Relocate this instruction.\n", encoding="utf-8")
        capabilities = self._capabilities()
        observed = capabilities["core-capability:filesystem.read"].handler(
            {"path": "AGENTS.md"},
            self.context,
            None,
        )
        source_digest = self._scope_digest(capabilities, "AGENTS.md")
        destination_digest = self._scope_digest(
            capabilities,
            "nested/AGENTS.md",
        )

        capabilities["core-capability:filesystem.move"].handler(
            {
                "source_path": "AGENTS.md",
                "destination_path": "nested/AGENTS.md",
                "expected_resource_identity": observed.payload[
                    "resource_identity"
                ],
                "expected_resource_revision": observed.payload[
                    "resource_revision"
                ],
                "source_instruction_scope_digest": source_digest,
                "destination_instruction_scope_digest": destination_digest,
            },
            self.context,
            None,
        )

        self.assertFalse(agents.exists())
        self.assertEqual(
            (destination_directory / "AGENTS.md").read_text(encoding="utf-8"),
            "Relocate this instruction.\n",
        )

    def test_search_cursor_and_versioned_mutations_fail_on_race(self) -> None:
        target = self.workspace / "race.txt"
        target.write_text("needle one\nneedle two\n", encoding="utf-8")
        capabilities = self._capabilities()
        first = capabilities["core-capability:filesystem.search"].handler(
            {"query": "needle", "max_results": 1},
            self.context,
            None,
        )
        target.write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeToolError, "filesystem_snapshot_changed"):
            capabilities["core-capability:filesystem.search"].handler(
                {"query": "ignored", "cursor": first.payload["next_cursor"]},
                self.context,
                None,
            )

        observed = capabilities["core-capability:filesystem.read"].handler(
            {"path": "race.txt"},
            self.context,
            None,
        )
        target.write_text("changed again\n", encoding="utf-8")
        scope_digest = self._scope_digest(capabilities, "race.txt")
        with self.assertRaisesRegex(RuntimeToolError, "filesystem_resource_changed"):
            capabilities["core-capability:filesystem.write"].handler(
                {
                    "path": "race.txt",
                    "content": "stale replacement",
                    "replace_only": True,
                    "expected_resource_identity": observed.payload[
                        "resource_identity"
                    ],
                    "expected_resource_revision": observed.payload[
                        "resource_revision"
                    ],
                    "instruction_scope_digest": scope_digest,
                },
                self.context,
                None,
            )
        self.assertEqual(target.read_text(encoding="utf-8"), "changed again\n")

    def test_recursive_delete_unlinks_symlink_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as outside_directory:
            outside = Path(outside_directory)
            protected = outside / "protected.txt"
            protected.write_text("outside", encoding="utf-8")
            tree = self.workspace / "tree"
            tree.mkdir()
            (tree / "local.txt").write_text("inside", encoding="utf-8")
            (tree / "link.txt").symlink_to(protected)
            capabilities = self._capabilities()
            scope_digest = self._scope_digest(
                capabilities,
                "tree",
                target_is_directory=True,
            )
            listing = capabilities["core-capability:filesystem.list"].handler(
                {"path": "."},
                self.context,
                None,
            )
            tree_entry = next(
                item
                for item in listing.payload["entries"]
                if item["path"] == "tree"
            )
            deleted = capabilities["core-capability:filesystem.delete"].handler(
                {
                    "path": "tree",
                    "recursive": True,
                    "expected_resource_identity": tree_entry["resource_identity"],
                    "expected_resource_revision": tree_entry["resource_revision"],
                    "instruction_scope_digest": scope_digest,
                },
                self.context,
                None,
            )
            self.assertEqual(deleted.payload["deleted_entry_count"], 3)
            self.assertTrue(protected.exists())
            self.assertEqual(protected.read_text(encoding="utf-8"), "outside")

    def test_shell_and_long_process_are_confined_streamed_and_reaped(self) -> None:
        capabilities = self._capabilities(processes=True)
        runtime_marker = self.workspace / "runtime" / "private-marker"
        runtime_marker.parent.mkdir(parents=True, exist_ok=True)
        runtime_marker.write_text("platform-private", encoding="utf-8")
        shell = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    (
                        "printf '%s|' \"$PWD\"; "
                        "test ! -e /etc/passwd && "
                        "test ! -e /workspace/runtime/private-marker && "
                        f"test ! -e {self.workspace!s} && printf confined"
                    ),
                ],
                "mutation_scopes": [],
            },
            self.context,
            None,
        )
        self.assertEqual(shell["output"], "/workspace|confined")

        fd_bypass = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/usr/bin/python3",
                    "-c",
                    (
                        "import os\n"
                        "for fd in range(3,128):\n"
                        " try:\n"
                        "  handle=os.open('descriptor-bypass.txt',"
                        "os.O_WRONLY|os.O_CREAT,0o600,dir_fd=fd)\n"
                        "  os.write(handle,b'bypass'); os.close(handle)\n"
                        " except OSError: pass\n"
                    ),
                ],
                "mutation_scopes": [],
            },
            self.context,
            None,
        )
        self.assertEqual(fd_bypass["exit_code"], 0)
        self.assertFalse((self.workspace / "descriptor-bypass.txt").exists())

        started = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    "read value; printf 'received:%s' \"$value\"",
                ],
                "mutation_scopes": [],
            },
            self.context,
            None,
        )
        process_id = started.payload["process_id"]
        capabilities["core-capability:process.input"].handler(
            {"process_id": process_id, "content": "hello\n", "close": True},
            self.context,
            None,
        )
        status = None
        for _ in range(50):
            status = capabilities["core-capability:process.status"].handler(
                {"process_id": process_id},
                self.context,
                None,
            )
            if status.payload["status"] == "exited":
                break
            time.sleep(0.02)
        assert status is not None
        self.assertEqual(status.payload["status"], "exited")
        self.assertEqual(status.payload["output"], "received:hello")
        self.assertFalse(runtime_processes_alive_for_session("session-hosted"))

    def test_shell_and_process_commit_only_declared_nested_instruction_scopes(self) -> None:
        nested = self.workspace / "nested"
        nested.mkdir()
        (self.workspace / "AGENTS.md").write_text("Root rules.\n", encoding="utf-8")
        (nested / "AGENTS.md").write_text("Nested rules.\n", encoding="utf-8")
        metadata_file = nested / "metadata.txt"
        metadata_file.write_text("unchanged", encoding="utf-8")
        capabilities = self._capabilities(processes=True)
        root_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )
        nested_digest = self._scope_digest(
            capabilities,
            "nested",
            target_is_directory=True,
        )

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_instruction_scope_changed",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "printf blocked > nested/shell-blocked.txt",
                    ],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": root_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertFalse((nested / "shell-blocked.txt").exists())

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_outside_declared_scope",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "printf blocked > outside-declared-scope.txt",
                    ],
                    "mutation_scopes": [
                        {
                            "path": "nested",
                            "instruction_scope_digest": nested_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertFalse((self.workspace / "outside-declared-scope.txt").exists())

        overlay_fd_bypass = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/usr/bin/python3",
                    "-c",
                    (
                        "import os\n"
                        "for fd in range(3,128):\n"
                        " try:\n"
                        "  handle=os.open('overlay-descriptor-bypass.txt',"
                        "os.O_WRONLY|os.O_CREAT,0o600,dir_fd=fd)\n"
                        "  os.write(handle,b'bypass'); os.close(handle)\n"
                        " except OSError: pass\n"
                    ),
                ],
                "mutation_scopes": [
                    {
                        "path": "nested",
                        "instruction_scope_digest": nested_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        self.assertEqual(overlay_fd_bypass["exit_code"], 0)
        self.assertFalse(
            (self.workspace / "overlay-descriptor-bypass.txt").exists()
        )

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_directory_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/sh",
                        "-c",
                        "mkdir -p nested/new && printf blocked > nested/new/file.txt",
                    ],
                    "mutation_scopes": [
                        {
                            "path": "nested",
                            "instruction_scope_digest": nested_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertFalse((nested / "new").exists())

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_directory_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": ["/bin/mkdir", "nested/empty-directory"],
                    "mutation_scopes": [
                        {
                            "path": "nested",
                            "instruction_scope_digest": nested_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertFalse((nested / "empty-directory").exists())

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_metadata_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": ["/bin/chmod", "700", "nested"],
                    "mutation_scopes": [
                        {
                            "path": "nested",
                            "instruction_scope_digest": nested_digest,
                        }
                    ],
                },
                self.context,
                None,
            )

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_metadata_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": ["/bin/chmod", "700", "nested/metadata.txt"],
                    "mutation_scopes": [
                        {
                            "path": "nested",
                            "instruction_scope_digest": nested_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertEqual(metadata_file.read_text(encoding="utf-8"), "unchanged")

        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_metadata_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/usr/bin/python3",
                        "-c",
                        (
                            "import os; "
                            "os.setxattr('nested/metadata.txt', "
                            "b'user.maverick.effect', b'ignored')"
                        ),
                    ],
                    "mutation_scopes": [
                        {
                            "path": "nested",
                            "instruction_scope_digest": nested_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        with self.assertRaises(OSError):
            os.getxattr(metadata_file, "user.maverick.effect")

        original_mtime_ns = metadata_file.stat().st_mtime_ns
        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_metadata_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": [
                        "/bin/touch",
                        "-t",
                        "200001010000",
                        "nested/metadata.txt",
                    ],
                    "mutation_scopes": [
                        {
                            "path": "nested",
                            "instruction_scope_digest": nested_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertEqual(metadata_file.stat().st_mtime_ns, original_mtime_ns)

        self.workspace.chmod(0o755)
        root_digest = self._scope_digest(
            capabilities,
            ".",
            target_is_directory=True,
        )
        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_effect_metadata_unsupported",
        ):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": ["/bin/chmod", "700", "."],
                    "mutation_scopes": [
                        {
                            "path": ".",
                            "instruction_scope_digest": root_digest,
                        }
                    ],
                },
                self.context,
                None,
            )
        self.assertEqual(stat.S_IMODE(self.workspace.stat().st_mode), 0o755)

        shell = capabilities["core-capability:shell.run"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    "printf allowed > nested/shell-allowed.txt",
                ],
                "mutation_scopes": [
                    {
                        "path": "nested",
                        "instruction_scope_digest": nested_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        self.assertEqual(shell["workspace_effect_paths"], ("nested/shell-allowed.txt",))
        self.assertEqual(
            (nested / "shell-allowed.txt").read_text(encoding="utf-8"),
            "allowed",
        )

        blocked = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    "printf blocked > nested/process-blocked.txt",
                ],
                "mutation_scopes": [
                    {
                        "path": ".",
                        "instruction_scope_digest": root_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        with self.assertRaisesRegex(
            RuntimeToolError,
            "workspace_instruction_scope_changed",
        ):
            self._wait_for_process(
                capabilities,
                str(blocked.payload["process_id"]),
            )
        blocked_record = self.harness.store.get_process(
            str(blocked.payload["process_id"])
        )
        self.assertEqual(blocked_record.status, "failed")
        self.assertEqual(
            blocked_record.failure_reason,
            "workspace_instruction_scope_changed",
        )
        self.assertFalse((nested / "process-blocked.txt").exists())

        allowed = capabilities["core-capability:process.start"].handler(
            {
                "argv": [
                    "/bin/sh",
                    "-c",
                    "printf allowed > nested/process-allowed.txt",
                ],
                "mutation_scopes": [
                    {
                        "path": "nested",
                        "instruction_scope_digest": nested_digest,
                    }
                ],
            },
            self.context,
            None,
        )
        allowed_status = self._wait_for_process(
            capabilities,
            str(allowed.payload["process_id"]),
        )
        self.assertEqual(allowed_status.payload["status"], "exited")
        self.assertTrue(
            allowed_status.payload["workspace_effects"][
                "workspace_effects_committed"
            ]
        )
        self.assertEqual(
            (nested / "process-allowed.txt").read_text(encoding="utf-8"),
            "allowed",
        )

    def test_shell_and_process_output_and_time_are_hard_bounded(self) -> None:
        capabilities = self._capabilities(processes=True)
        with self.assertRaisesRegex(RuntimeToolError, "shell_output_too_large"):
            capabilities["core-capability:shell.run"].handler(
                {
                    "argv": ["/usr/bin/head", "-c", "200000", "/dev/zero"],
                    "mutation_scopes": [],
                },
                self.context,
                None,
            )

        with patch("core.runtime.hosted_process_output.MAX_PROCESS_OUTPUT_BYTES", 64):
            overflowing = capabilities["core-capability:process.start"].handler(
                {
                    "argv": ["/usr/bin/head", "-c", "1024", "/dev/zero"],
                    "timeout_seconds": 5,
                    "mutation_scopes": [],
                },
                self.context,
                None,
            )
            overflow_status = self._wait_for_process(
                capabilities,
                str(overflowing.payload["process_id"]),
            )
        self.assertEqual(overflow_status.payload["status"], "failed")
        self.assertEqual(
            overflow_status.payload["failure_reason"],
            "process_output_too_large",
        )
        self.assertTrue(overflow_status.payload["output_truncated"])

        timing_out = capabilities["core-capability:process.start"].handler(
            {
                "argv": ["/bin/sh", "-c", "sleep 10"],
                "timeout_seconds": 1,
                "mutation_scopes": [],
            },
            self.context,
            None,
        )
        timeout_status = self._wait_for_process(
            capabilities,
            str(timing_out.payload["process_id"]),
        )
        self.assertEqual(timeout_status.payload["status"], "timed-out")
        self.assertEqual(
            timeout_status.payload["failure_reason"],
            "process_timed_out",
        )
        self.assertFalse(runtime_processes_alive_for_session("session-hosted"))

    def test_cli_and_mcp_require_discovery_token_across_catalog_refresh(self) -> None:
        cli = CliCommandRegistry()
        cli.register_command(
            CliCommandDefinition(
                command_id="fixture.echo",
                path_segments=["fixture", "echo"],
                description="Echo a fixture.",
                argument_schema={"type": "object"},
                owner_kind="core",
                owner_id="core",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=CliInvocationPolicy(
                    operator_only=False,
                    required_platform_role=None,
                    sandbox_agent_allowed=True,
                    requires_workspace_context=True,
                    requires_full_access=False,
                ),
                entrypoint_path=None,
                effect_class="read",
                safe_to_retry=True,
                schema_public=True,
                certified_tcb_component="tool-schema-catalog",
            ),
            lambda arguments, _context: {"echo": arguments.get("value")},
        )
        mcp = McpToolRegistry()
        mcp.register_tool(
            McpToolDefinition(
                tool_name="fixture_lookup",
                description="Lookup a fixture.",
                input_schema={"type": "object"},
                output_schema=None,
                owner_kind="core",
                owner_id="core",
                workspace_id=None,
                exposure_scope="core_global",
                invocation_policy=McpInvocationPolicy(
                    operator_only=False,
                    sandbox_agent_allowed=True,
                    requires_workspace_context=True,
                    requires_full_access=False,
                ),
                entrypoint_path=None,
                effect_class="read",
                safe_to_retry=True,
                schema_public=True,
                certified_tcb_component="tool-schema-catalog",
            ),
            lambda arguments, _context: {"found": arguments.get("id")},
        )
        first = self._discovery(cli, mcp)
        cli_listing = first["core-capability:cli.list"].handler(
            {}, self.context, None
        )
        mcp_listing = first["core-capability:mcp.list"].handler(
            {}, self.context, None
        )

        refreshed = self._discovery(cli, mcp)
        cli_result = refreshed["core-capability:cli.run"].handler(
            {
                "command_id": "fixture.echo",
                "invocation_token": cli_listing.payload["commands"][0][
                    "invocation_token"
                ],
                "arguments": {"value": "ok"},
            },
            self.context,
            None,
        )
        mcp_result = refreshed["core-capability:mcp.call"].handler(
            {
                "tool_name": "fixture_lookup",
                "invocation_token": mcp_listing.payload["tools"][0][
                    "invocation_token"
                ],
                "arguments": {"id": 7},
            },
            self.context,
            None,
        )
        self.assertEqual(cli_result.payload, {"echo": "ok"})
        self.assertEqual(mcp_result.payload, {"found": 7})
        with self.assertRaisesRegex(RuntimeToolError, "tool_discovery_required"):
            refreshed["core-capability:cli.run"].handler(
                {
                    "command_id": "fixture.echo",
                    "arguments": {},
                },
                self.context,
                None,
            )

    def _capabilities(self, *, processes: bool = False, race_hook=None):
        surfaces = build_core_runtime_tool_capabilities(
            workspace_id="default",
            workspace_root=self.workspace,
            runtime_root=Path(self.harness.session.runtime_root),
            process_registry=(
                HostedToolProcessRegistry(store=self.harness.store)
                if processes
                else None
            ),
            filesystem_race_hook=race_hook,
        )
        return {surface.definition.handle: surface for surface in surfaces}

    def _wait_for_process(self, capabilities, process_id: str):
        status = None
        for _ in range(150):
            status = capabilities["core-capability:process.status"].handler(
                {"process_id": process_id},
                self.context,
                None,
            )
            if status.payload["status"] != "running":
                return status
            time.sleep(0.02)
        self.fail(f"process {process_id} did not reach a terminal status")

    def _scope_digest(
        self,
        capabilities,
        path: str,
        *,
        target_is_directory: bool = False,
    ) -> str:
        result = capabilities[
            "core-capability:workspace.instructions"
        ].handler(
            {
                "path": path,
                "target_is_directory": target_is_directory,
            },
            self.context,
            None,
        )
        return str(result.payload["scope_digest"])

    @staticmethod
    def _discovery(cli, mcp):
        return {
            surface.definition.handle: surface
            for surface in build_discovery_first_capabilities(
                cli_registry=cli,
                mcp_registry=mcp,
            )
        }


if __name__ == "__main__":
    unittest.main()
