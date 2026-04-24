"""Tests for source-buildable app frontend discovery."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_app_frontends import _rebuildable_app_roots


class BuildAppFrontendsTestCase(unittest.TestCase):
    def test_rebuildable_app_roots_skip_dist_only_apps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            apps_root = Path(temp_dir) / "apps"
            buildable = apps_root / "buildable"
            dist_only = apps_root / "dist-only"
            _write_app(buildable, rebuild=True, build_script="tsc --noEmit && vite build")
            _write_app(dist_only, rebuild=False, build_script='node -e "require(\'fs\').accessSync(\'frontend/dist/index.html\')"')

            self.assertEqual(_rebuildable_app_roots(apps_root), [buildable])

    def test_rebuildable_app_roots_reject_noop_rebuild_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            apps_root = Path(temp_dir) / "apps"
            app_root = apps_root / "fake-build"
            _write_app(app_root, rebuild=True, build_script='node -e "process.exit(0)"')

            with self.assertRaises(SystemExit):
                _rebuildable_app_roots(apps_root)


def _write_app(app_root: Path, *, rebuild: bool, build_script: str) -> None:
    app_root.mkdir(parents=True)
    (app_root / "frontend" / "dist").mkdir(parents=True)
    (app_root / "frontend" / "dist" / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
    (app_root / "package.json").write_text(json.dumps({"scripts": {"build": build_script}}), encoding="utf-8")
    (app_root / "app_contract.json").write_text(
        json.dumps(
            {
                "app_id": app_root.name,
                "entrypoints": {"frontend": "frontend/dist"},
                "lifecycle": {"rebuild": rebuild},
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
