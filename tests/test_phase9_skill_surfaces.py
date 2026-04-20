"""Split tests from tests/test_phase9_surfaces.py."""

from __future__ import annotations

import json

from tests.phase9_surfaces_helpers import *


class TestPhase9SkillSurfaces(Phase9SurfacesBase):
    """Focused test slice."""

    def test_visible_skills_come_from_workspace_skills_data(self) -> None:
        repo_root = self.make_repo_root()
        skill_root = repo_root / "workspaces" / "default" / "data" / "skills" / "skills" / "task-helper"
        skill_root.mkdir(parents=True)
        skill_root.joinpath("SKILL.md").write_text(
            "---\nname: Task Helper\ndescription: Use for task work.\n---\n\n# Task Helper\n",
            encoding="utf-8",
        )
        disabled_root = repo_root / "workspaces" / "default" / "data" / "skills" / "skills" / "disabled-helper"
        disabled_root.mkdir(parents=True)
        disabled_root.joinpath("SKILL.md").write_text("# Disabled Helper\n", encoding="utf-8")
        state_path = repo_root / "workspaces" / "default" / "data" / "skills" / "state.json"
        state_path.write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "skills": [
                        {"id": "task-helper", "name": "Task Helper", "description": "Use for task work.", "enabled": True},
                        {"id": "disabled-helper", "name": "Disabled Helper", "enabled": False},
                    ],
                }
            ),
            encoding="utf-8",
        )

        skills = list_available_workspace_skills(workspace_id="default", start_path=repo_root)

        self.assertEqual([skill.skill_id for skill in skills], ["task-helper"])
        self.assertEqual(skills[0].name, "Task Helper")
        self.assertEqual(skills[0].description, "Use for task work.")
        self.assertEqual(skills[0].owner_kind, "workspace")
        self.assertEqual(skills[0].workspace_id, "default")

    def test_provider_adapter_materializes_skills_into_provider_specific_runtime_home(self) -> None:
        provider_store = self.make_provider_store()
        runtime_store = self.make_runtime_store()
        register_builtin_providers(provider_store)
        now = datetime.now(tz=UTC)
        repo_root = self.make_repo_root()
        skill_root = repo_root / "workspaces" / "default" / "data" / "skills" / "skills" / "task-helper"
        skill_root.mkdir(parents=True)
        skill_root.joinpath("SKILL.md").write_text("# Task Helper\n", encoding="utf-8")
        session = create_runtime_session(
            runtime_store,
            session_id="sess-1",
            workspace_id="default",
            agent_id="agent-1",
            now=now,
            requested_mode="sandbox",
            start_path=repo_root,
        )
        skills = list_available_workspace_skills(workspace_id=session.workspace_id, start_path=repo_root)

        materializations = prepare_runtime_skills(provider_store, session=session, skills=skills, codex_command="/bin/echo")

        target_roots = [Path(item.target_root) for item in materializations]
        self.assertEqual(len(target_roots), 1)
        self.assertTrue(target_roots[0].as_posix().endswith("/skills/task-helper"))
        self.assertTrue(all(item.strategy == "copy" for item in materializations))
        for path in target_roots:
            self.assertTrue(path.is_dir())
            self.assertFalse(path.is_symlink())
            self.assertIn("codex-home", path.parts)
            codex_home_index = path.parts.index("codex-home")
            self.assertEqual(path.parts[codex_home_index + 1], "skills")

    def test_runtime_skill_resolution_rejects_missing_workspace_skills(self) -> None:
        runtime_store = self.make_runtime_store()
        repo_root = self.make_repo_root()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-1",
            workspace_id="default",
            agent_id="agent-1",
            now=datetime.now(tz=UTC),
            requested_mode="sandbox",
            start_path=repo_root,
            skill_ids=["missing-helper"],
        )

        with self.assertRaises(ValueError):
            resolve_runtime_skills(session, start_path=repo_root)
