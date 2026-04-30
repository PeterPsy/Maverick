"""Tests for repository-local path rebasing helpers."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from core.shared.path_rebasing import rebase_local_state_paths, rebase_repository_path


class PathRebasingTestCase(unittest.TestCase):
    def test_rebase_repository_path_rewrites_old_repository_root(self) -> None:
        repository_root = Path("/tmp/new-checkout")
        original = "/old-checkout/maverick/workspaces/default/apps/simple-calculator"

        rebased = rebase_repository_path(original, repository_root=repository_root)

        self.assertEqual(rebased, str(repository_root / "workspaces/default/apps/simple-calculator"))

    def test_rebase_repository_path_leaves_non_repository_absolute_paths_unchanged(self) -> None:
        repository_root = Path("/tmp/new-checkout")
        original = "/var/tmp/not-maverick/example.txt"

        rebased = rebase_repository_path(original, repository_root=repository_root)

        self.assertEqual(rebased, original)

    def test_rebase_local_state_paths_updates_known_json_documents(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-rebase-") as temp_dir:
            repository_root = Path(temp_dir)
            (repository_root / "AGENTS.md").write_text("", encoding="utf-8")
            (repository_root / "core").mkdir()
            (repository_root / "apps").mkdir()
            (repository_root / "workspaces" / "default" / "data" / "skills").mkdir(parents=True)
            app_state_root = repository_root / "data" / "control-plane" / "json" / "apps"
            app_state_root.mkdir(parents=True)

            old_root = Path("/old-checkout/maverick")
            (app_state_root / "app_sources.json").write_text(
                json.dumps([{"source_path": str(old_root / "apps" / "sample-app")}], indent=2) + "\n",
                encoding="utf-8",
            )
            (app_state_root / "workspace_local_app_projects.json").write_text(
                json.dumps(
                    [{"project_root": str(old_root / "workspaces" / "default" / "apps" / "simple-calculator")}],
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (app_state_root / "workspace_app_bindings.json").write_text(
                json.dumps([{"data_root": str(old_root / "workspaces" / "default" / "data" / "sample-app")}], indent=2)
                + "\n",
                encoding="utf-8",
            )
            skill_state_path = repository_root / "workspaces" / "default" / "data" / "skills" / "state.json"
            skill_state_path.write_text(
                json.dumps([{"source_path": str(old_root / "workspaces" / "default" / "data" / "skills" / "skills" / "sample-skill" / "SKILL.md")}], indent=2)
                + "\n",
                encoding="utf-8",
            )

            changed_paths = rebase_local_state_paths(start_path=repository_root)

            self.assertEqual(
                sorted(path.relative_to(repository_root).as_posix() for path in changed_paths),
                [
                    "data/control-plane/json/apps/app_sources.json",
                    "data/control-plane/json/apps/workspace_app_bindings.json",
                    "data/control-plane/json/apps/workspace_local_app_projects.json",
                    "workspaces/default/data/skills/state.json",
                ],
            )
            self.assertIn(str(repository_root / "apps" / "sample-app"), (app_state_root / "app_sources.json").read_text())
            self.assertIn(
                str(repository_root / "workspaces" / "default" / "apps" / "simple-calculator"),
                (app_state_root / "workspace_local_app_projects.json").read_text(),
            )
            self.assertIn(
                str(repository_root / "workspaces" / "default" / "data" / "sample-app"),
                (app_state_root / "workspace_app_bindings.json").read_text(),
            )
            self.assertIn(
                str(repository_root / "workspaces" / "default" / "data" / "skills" / "skills" / "sample-skill" / "SKILL.md"),
                skill_state_path.read_text(),
            )


if __name__ == "__main__":
    unittest.main()
