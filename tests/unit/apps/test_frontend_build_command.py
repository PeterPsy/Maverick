"""Tests for source-buildable app frontend discovery."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.build_app_frontends import _frontend_app_build_roots, main as build_frontends_main


class BuildAppFrontendsTestCase(unittest.TestCase):
    def test_frontend_app_build_roots_include_every_frontend_app(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            apps_root = Path(temp_dir) / "apps"
            buildable = apps_root / "buildable"
            frontend_package = apps_root / "frontend-package"
            no_frontend = apps_root / "no-frontend"
            _write_app(buildable, build_script="tsc --noEmit && vite build")
            _write_app(frontend_package, build_script="vite build", package_root="frontend")
            _write_app(no_frontend, build_script="node scripts/build.mjs", frontend=False)

            self.assertEqual(_frontend_app_build_roots(apps_root), [buildable, frontend_package / "frontend"])

    def test_frontend_app_build_roots_reject_noop_build_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            apps_root = Path(temp_dir) / "apps"
            app_root = apps_root / "fake-build"
            _write_app(app_root, build_script='node -e "process.exit(0)"')

            with self.assertRaises(SystemExit):
                _frontend_app_build_roots(apps_root)

    def test_frontend_build_main_requires_supported_node_runtime(self) -> None:
        with patch("scripts.build_app_frontends.require_supported_node_runtime", side_effect=RuntimeError("node old")):
            with self.assertRaises(SystemExit) as captured:
                build_frontends_main([])

        self.assertIn("Node.js 24 LTS", str(captured.exception))
        self.assertIn("node old", str(captured.exception))

    def test_frontend_build_script_direct_help_invocation_resolves_core_imports(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [sys.executable, str(repo_root / "scripts" / "build_app_frontends.py"), "--help"],
                cwd=temp_dir,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage: build_app_frontends.py", completed.stdout)


def _write_app(app_root: Path, *, build_script: str, frontend: bool = True, package_root: str = ".") -> None:
    app_root.mkdir(parents=True)
    package_dir = app_root if package_root == "." else app_root / package_root
    package_dir.mkdir(parents=True, exist_ok=True)
    if frontend:
        (app_root / "frontend" / "dist").mkdir(parents=True)
        (app_root / "frontend" / "dist" / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
    package_json = package_dir / "package.json"
    package_json.write_text(json.dumps({"scripts": {"build": build_script}}), encoding="utf-8")
    entrypoints = {"frontend": "frontend/dist"} if frontend else {}
    (app_root / "app_contract.json").write_text(
        json.dumps(
            {
                "app_id": app_root.name,
                "entrypoints": entrypoints,
                "lifecycle": {},
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
