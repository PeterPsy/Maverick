from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

from core.runtime.tool_errors import RuntimeToolError
from tests.support.cases.full_workspace_contract import FullWorkspaceContractFixture


class FullWorkspaceContractTest(FullWorkspaceContractFixture, unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
