"""Split tests from tests/test_phase9_surfaces.py."""

from __future__ import annotations

from tests.phase9_surfaces_helpers import *


class TestPhase9SkillSurfaces(Phase9SurfacesBase):
    """Focused test slice."""

    def test_visible_skills_merge_core_and_enabled_app_skills(self) -> None:
        store = self.make_app_store()
        now = datetime.now(tz=UTC)
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root)
        source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(app_root),
            now=now,
        )
        install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)

        skills = list_visible_platform_skills(app_store=store, workspace_id="default", start_path=repo_root)

        self.assertIn("core.core-ops", [skill.skill_id for skill in skills])
        self.assertIn("app.checklists.task-helper", [skill.skill_id for skill in skills])

    def test_provider_adapter_materializes_skills_into_provider_specific_runtime_home(self) -> None:
        app_store = self.make_app_store()
        provider_store = self.make_provider_store()
        runtime_store = self.make_runtime_store()
        register_builtin_providers(provider_store)
        now = datetime.now(tz=UTC)
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root)
        source = register_app_source_from_contract(
            app_store,
            source_kind="platform",
            source_path=str(app_root),
            now=now,
        )
        install_store_app(app_store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)
        session = create_runtime_session(
            runtime_store,
            session_id="sess-1",
            workspace_id="default",
            agent_id="agent-1",
            now=now,
            requested_mode="sandbox",
            start_path=repo_root,
        )
        skills = list_visible_platform_skills(app_store=app_store, workspace_id="default", start_path=repo_root)

        materializations = prepare_runtime_skills(provider_store, session=session, skills=skills, codex_command="/bin/echo")

        target_roots = [Path(item.target_root) for item in materializations]
        self.assertTrue(any(path.as_posix().endswith("/core/core-ops") for path in target_roots))
        self.assertTrue(any(path.as_posix().endswith("/app/checklists/task-helper") for path in target_roots))
        self.assertTrue(all(item.strategy == "copy" for item in materializations))
        for path in target_roots:
            self.assertTrue(path.is_dir())
            self.assertFalse(path.is_symlink())
            self.assertIn("codex-home", path.parts)
            codex_home_index = path.parts.index("codex-home")
            self.assertEqual(path.parts[codex_home_index + 1], "skills")

    def test_skill_ids_are_namespaced_to_avoid_core_app_collisions(self) -> None:
        store = self.make_app_store()
        now = datetime.now(tz=UTC)
        repo_root = self.make_repo_root()
        app_root = repo_root / "apps" / "checklists"
        self.write_app_contract(app_root, skill_id="core-ops")
        source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(app_root),
            now=now,
        )
        install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)

        skills = list_visible_platform_skills(app_store=store, workspace_id="default", start_path=repo_root)

        self.assertIn("core.core-ops", [skill.skill_id for skill in skills])
        self.assertIn("app.checklists.core-ops", [skill.skill_id for skill in skills])
