from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.skills.catalog import list_workspace_skills
from core.skills.models import SkillDefinition
from core.skills.service import SkillInvocationError, resolve_invoked_runtime_skills
from tests.support.repo import make_temp_repo_root


class RuntimeSkillInvocationTestCase(unittest.TestCase):
    def session(self, *, skill_ids: list[str] | None = None):
        return SimpleNamespace(
            workspace_id="default",
            skill_ids=skill_ids or [],
            skill_catalog_app_id="skills",
        )

    def test_session_allowlist_is_enforced_before_catalog_resolution(self) -> None:
        with self.assertRaisesRegex(SkillInvocationError, "outside the session allowlist") as raised:
            resolve_invoked_runtime_skills(self.session(skill_ids=["allowed"]), ["denied"])
        self.assertEqual(raised.exception.reason_code, "invoked_skill_not_allowed")

    def test_unknown_or_disabled_skill_is_reported_as_unavailable(self) -> None:
        with patch("core.skills.service.resolve_workspace_skills", side_effect=ValueError("unknown")):
            with self.assertRaises(SkillInvocationError) as raised:
                resolve_invoked_runtime_skills(self.session(), ["missing"])
        self.assertEqual(raised.exception.reason_code, "invoked_skill_unavailable")

    def test_stable_ids_are_deduplicated_in_request_order(self) -> None:
        definitions = {
            skill_id: SkillDefinition(
                skill_id=skill_id,
                local_skill_id=skill_id,
                name=skill_id,
                description=skill_id,
                source_root=f"/catalog/{skill_id}",
                owner_kind="workspace",
                owner_id="default",
                workspace_id="default",
                status="available",
            )
            for skill_id in ("one", "two")
        }

        def resolve(**kwargs):
            return [definitions[skill_id] for skill_id in kwargs["skill_ids"]]

        with patch("core.skills.service.resolve_workspace_skills", side_effect=resolve) as resolver:
            result = resolve_invoked_runtime_skills(self.session(), ["two", "one", "two"])

        self.assertEqual([item.skill_id for item in result], ["two", "one"])
        self.assertEqual(resolver.call_args.kwargs["skill_ids"], ["two", "one"])

    def test_catalog_never_publishes_directory_or_skill_file_symlinks(self) -> None:
        root = make_temp_repo_root(self)
        skills_root = (
            root / "workspaces" / "default" / "data" / "skills" / "skills"
        )
        real = skills_root / "real-skill"
        real.mkdir(parents=True)
        (real / "SKILL.md").write_text("# Real\n", encoding="utf-8")
        (skills_root / "alias-skill").symlink_to(
            real,
            target_is_directory=True,
        )
        linked_file = skills_root / "linked-file"
        linked_file.mkdir()
        (linked_file / "SKILL.md").symlink_to(real / "SKILL.md")

        skills = list_workspace_skills(
            workspace_id="default",
            start_path=root,
        )

        self.assertEqual([item.skill_id for item in skills], ["real-skill"])
        self.assertEqual(skills[0].source_root, str(Path(real).absolute()))


if __name__ == "__main__":
    unittest.main()
