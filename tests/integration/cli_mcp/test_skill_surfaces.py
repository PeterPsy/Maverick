"""Split tests from surface helper module."""

from __future__ import annotations

import json

from core.apps.contracts import build_provided_interface_declaration, build_required_interface_declaration
from core.apps.dependencies import save_app_dependency_selection
from core.apps.errors import AppHostingError
from core.skills.runtime_catalog import runtime_skill_catalog_app_id_for_request
from tests.support.surfaces import *


class TestSkillSurfaces(SurfaceTestBase):
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
        configure_workspace_provider(provider_store, workspace_id="default", provider_id="codex", codex_command="/bin/echo")
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

    def test_runtime_skill_resolution_uses_session_skill_catalog_app_id(self) -> None:
        runtime_store = self.make_runtime_store()
        repo_root = self.make_repo_root()
        custom_skill_root = repo_root / "workspaces" / "default" / "data" / "custom-skills" / "skills" / "task-helper"
        custom_skill_root.mkdir(parents=True)
        custom_skill_root.joinpath("SKILL.md").write_text(
            "---\nname: Custom Task Helper\ndescription: Use custom skill provider.\n---\n\n# Custom Task Helper\n",
            encoding="utf-8",
        )
        session = create_runtime_session(
            runtime_store,
            session_id="sess-custom-skills",
            workspace_id="default",
            agent_id="agent-1",
            now=datetime.now(tz=UTC),
            requested_mode="sandbox",
            start_path=repo_root,
            skill_ids=["task-helper"],
            skill_catalog_app_id="custom-skills",
        )

        skills = resolve_runtime_skills(session, start_path=repo_root)

        self.assertEqual([skill.skill_id for skill in skills], ["task-helper"])
        self.assertIn("/data/custom-skills/skills/task-helper", skills[0].source_root)

    def test_runtime_skill_catalog_provider_resolves_from_source_app_dependency(self) -> None:
        app_store = self.make_app_store()
        repo_root = self.make_repo_root()
        provider_root = repo_root / "apps" / "custom-skills"
        consumer_root = repo_root / "apps" / "runtime-consumer"
        write_app_contract_file(
            provider_root,
            build_parsed_app_contract(
                app_id="custom-skills",
                name="Custom Skills",
                version="1.0.0",
                description="Custom skill catalog provider.",
                publisher="maverick",
                contract=build_app_contract(
                    provides=[
                        build_provided_interface_declaration(
                            interface="skill.catalog",
                            description="Custom workspace skill catalog.",
                        )
                    ]
                ),
            ),
        )
        write_app_contract_file(
            consumer_root,
            build_parsed_app_contract(
                app_id="runtime-consumer",
                name="Runtime Consumer",
                version="1.0.0",
                description="Runtime consumer app.",
                publisher="maverick",
                contract=build_app_contract(
                    requires=[
                        build_required_interface_declaration(
                            alias="runtime-skills",
                            interface="skill.catalog",
                            description="Runtime skill catalog.",
                        )
                    ]
                ),
            ),
        )
        for app_root in (provider_root, consumer_root):
            source = register_app_source_from_contract(app_store, source_kind="platform", source_path=str(app_root))
            install_store_app(app_store, source_id=source.source_id, workspace_id="default", start_path=repo_root)
        save_app_dependency_selection(
            app_store,
            workspace_id="default",
            consumer_app_id="runtime-consumer",
            alias="runtime-skills",
            provider_app_ids=["custom-skills"],
            start_path=repo_root,
        )

        provider_app_id = runtime_skill_catalog_app_id_for_request(
            app_store,
            workspace_id="default",
            source_app_id="runtime-consumer",
            start_path=repo_root,
        )

        self.assertEqual(provider_app_id, "custom-skills")

    def test_explicit_runtime_skill_catalog_provider_must_provide_skill_catalog(self) -> None:
        app_store = self.make_app_store()
        repo_root = self.make_repo_root()
        provider_root = repo_root / "apps" / "custom-skills"
        write_app_contract_file(
            provider_root,
            build_parsed_app_contract(
                app_id="custom-skills",
                name="Custom Skills",
                version="1.0.0",
                description="Custom skill catalog provider.",
                publisher="maverick",
                contract=build_app_contract(
                    provides=[
                        build_provided_interface_declaration(
                            interface="skill.catalog",
                            description="Custom workspace skill catalog.",
                        )
                    ]
                ),
            ),
        )
        source = register_app_source_from_contract(app_store, source_kind="platform", source_path=str(provider_root))
        install_store_app(app_store, source_id=source.source_id, workspace_id="default", start_path=repo_root)

        provider_app_id = runtime_skill_catalog_app_id_for_request(
            app_store,
            workspace_id="default",
            explicit_app_id="custom-skills",
            start_path=repo_root,
        )
        with self.assertRaisesRegex(AppHostingError, "not an enabled `skill.catalog` provider"):
            runtime_skill_catalog_app_id_for_request(
                app_store,
                workspace_id="default",
                explicit_app_id="missing-skills",
                start_path=repo_root,
            )

        self.assertEqual(provider_app_id, "custom-skills")
