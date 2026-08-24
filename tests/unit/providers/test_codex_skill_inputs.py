from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.providers.codex_skill_inputs import codex_provider_input_text, codex_skill_input_items
from core.providers.errors import ProviderLaunchError
from core.skills.models import SkillDefinition


def skill(skill_id: str = "storage-ops") -> SkillDefinition:
    return SkillDefinition(
        skill_id=skill_id,
        local_skill_id=skill_id,
        name="Storage Ops",
        description="Operate Storage.",
        source_root="/untrusted/catalog/path",
        owner_kind="workspace",
        owner_id="default",
        workspace_id="default",
        status="available",
    )


class CodexSkillInputTestCase(unittest.TestCase):
    def test_explicit_mode_neutralizes_unstructured_codex_skill_mentions_only_in_provider_copy(self) -> None:
        input_text = "Use $storage-ops and [$crm:search](skill://crm:search), but keep $HOME, $ and €5."

        provider_text = codex_provider_input_text(input_text, skill_activation_mode="explicit")

        self.assertEqual(
            provider_text,
            "Use ＄storage-ops and [＄crm:search](skill://crm:search), but keep $HOME, $ and €5.",
        )
        self.assertEqual(
            input_text,
            "Use $storage-ops and [$crm:search](skill://crm:search), but keep $HOME, $ and €5.",
        )

    def test_implicit_mode_preserves_codex_skill_mentions(self) -> None:
        self.assertEqual(
            codex_provider_input_text("Use $storage-ops", skill_activation_mode="implicit"),
            "Use $storage-ops",
        )

    def test_uses_only_materialized_runtime_skill_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir) / "runtime"
            skill_file = runtime_root / "codex-home" / "skills" / "storage-ops" / "SKILL.md"
            skill_file.parent.mkdir(parents=True)
            skill_file.write_text("# Storage Ops\n", encoding="utf-8")

            items = codex_skill_input_items(runtime_root, [skill()])

        self.assertEqual(items, [{"type": "skill", "name": "storage-ops", "path": str(skill_file.resolve())}])
        self.assertNotEqual(items[0]["path"], "/untrusted/catalog/path/SKILL.md")

    def test_missing_runtime_copy_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir) / "runtime"
            (runtime_root / "codex-home" / "skills").mkdir(parents=True)
            with self.assertRaisesRegex(ProviderLaunchError, "invoked_skill_runtime_path_missing"):
                codex_skill_input_items(runtime_root, [skill()])

    def test_symlink_escape_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime_root = root / "runtime"
            skills_root = runtime_root / "codex-home" / "skills"
            outside = root / "outside"
            outside.mkdir()
            (outside / "SKILL.md").write_text("# Outside\n", encoding="utf-8")
            skills_root.mkdir(parents=True)
            (skills_root / "storage-ops").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ProviderLaunchError, "invoked_skill_runtime_path_unsafe"):
                codex_skill_input_items(runtime_root, [skill()])


if __name__ == "__main__":
    unittest.main()
