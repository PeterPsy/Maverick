"""Tests for built-in app bootstrap behavior."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.apps.builtin_apps import register_and_install_builtin_apps_for_active_workspaces
from core.apps.contracts import (
    build_app_compatibility,
    build_app_contract,
    build_app_entrypoints,
    build_parsed_app_contract,
    write_app_contract_file,
)
from core.apps.errors import WorkspaceAppBindingNotFoundError
from core.apps.service import transition_workspace_app_status
from core.apps.store import AppCollections, AppDocumentStore
from core.workspaces.service import create_workspace, ensure_default_workspace_record
from core.workspaces.store import WorkspaceDocumentStore, WorkspaceCollections
from tests.support.collections import FakeCollection


class BuiltinAppBootstrapTests(unittest.TestCase):
    def test_static_bundled_frontends_have_build_package_json(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        violations: list[str] = []
        for contract_path in sorted((repo_root / "apps").glob("*/app_contract.json")):
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            frontend = str(contract.get("entrypoints", {}).get("frontend") or "")
            if not frontend:
                continue
            app_root = contract_path.parent
            frontend_root = app_root / frontend.split("/", 1)[0]
            if not (frontend_root / "package.json").is_file() and not (app_root / "package.json").is_file():
                violations.append(contract_path.parent.name)

        self.assertEqual(violations, [])

    def test_bundled_app_compatibility_is_specific_not_blanket_full_access(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        violations: list[str] = []
        for contract_path in sorted((repo_root / "apps").glob("*/app_contract.json")):
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            modes = contract.get("compatibility", {}).get("workspace_modes") or []
            if "full-access" in modes and "sandbox" in modes:
                violations.append(contract_path.parent.name)

        self.assertEqual(violations, [])

    def test_incompatible_builtin_app_is_skipped_for_sandbox_workspace(self) -> None:
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = _make_repo_root(Path(temp_dir))
            _write_contract(repo_root / "apps" / "portable", ["sandbox"])
            _write_contract(repo_root / "apps" / "operator-monitor", ["full-access"])
            app_store = _make_app_store()
            workspace_store = _make_workspace_store()
            ensure_default_workspace_record(workspace_store, now=now)
            create_workspace(workspace_store, name="CEIDA", created_by_user_id="user:admin", now=now)

            with self.assertLogs("core.apps.builtin_apps", level="WARNING") as logs:
                installed_by_workspace = register_and_install_builtin_apps_for_active_workspaces(
                    app_store,
                    workspace_store,
                    start_path=repo_root,
                    now=now,
                )

            self.assertEqual(installed_by_workspace["default"], ["operator-monitor", "portable"])
            self.assertEqual(installed_by_workspace["ceida"], ["portable"])
            self.assertTrue(any("operator-monitor" in message and "ceida" in message for message in logs.output))
            self.assertIsNotNone(app_store.get_workspace_app_binding(workspace_id="default", app_id="operator-monitor"))
            with self.assertRaises(WorkspaceAppBindingNotFoundError):
                app_store.get_workspace_app_binding(workspace_id="ceida", app_id="operator-monitor")

    def test_current_builtin_binding_does_not_rerun_install_hook(self) -> None:
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = _make_repo_root(Path(temp_dir))
            app_root = repo_root / "apps" / "hooked"
            _write_contract(app_root, ["sandbox"], hooks={"install": "backend/install.py"})
            install_hook = app_root / "backend" / "install.py"
            install_hook.parent.mkdir(parents=True, exist_ok=True)
            install_hook.write_text(
                "\n".join(
                    [
                        "from pathlib import Path",
                        "counter = Path('install-count.txt')",
                        "count = int(counter.read_text(encoding='utf-8')) if counter.exists() else 0",
                        "counter.write_text(str(count + 1), encoding='utf-8')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            app_store = _make_app_store()
            workspace_store = _make_workspace_store()

            first = register_and_install_builtin_apps_for_active_workspaces(
                app_store,
                workspace_store,
                start_path=repo_root,
                now=now,
            )
            second = register_and_install_builtin_apps_for_active_workspaces(
                app_store,
                workspace_store,
                start_path=repo_root,
                now=now,
            )

            self.assertEqual(first["default"], ["hooked"])
            self.assertEqual(second["default"], ["hooked"])
            self.assertEqual((app_root / "install-count.txt").read_text(encoding="utf-8"), "1")

    def test_disabled_builtin_binding_is_not_reenabled_on_bootstrap(self) -> None:
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = _make_repo_root(Path(temp_dir))
            _write_contract(repo_root / "apps" / "workspace-tool", ["sandbox"])
            app_store = _make_app_store()
            workspace_store = _make_workspace_store()

            register_and_install_builtin_apps_for_active_workspaces(
                app_store,
                workspace_store,
                start_path=repo_root,
                now=now,
            )
            transition_workspace_app_status(
                app_store,
                workspace_id="default",
                app_id="workspace-tool",
                target_status="disabled",
                now=now,
            )
            register_and_install_builtin_apps_for_active_workspaces(
                app_store,
                workspace_store,
                start_path=repo_root,
                now=now,
            )

            binding = app_store.get_workspace_app_binding(workspace_id="default", app_id="workspace-tool")
            self.assertEqual(binding.status, "disabled")


def _make_repo_root(root: Path) -> Path:
    (root / "AGENTS.md").write_text("test", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = \"maverick\"\nversion = \"0.1.0\"\n", encoding="utf-8")
    for name in ("apps", "core", "docs", "scripts", "tests", "workspaces"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _write_contract(app_root: Path, workspace_modes: list[str], *, hooks: dict[str, str] | None = None) -> None:
    parsed = build_parsed_app_contract(
        app_id=app_root.name,
        name=app_root.name.title(),
        version="1.0.0",
        description=f"{app_root.name} app",
        publisher="maverick",
        contract=build_app_contract(
            compatibility=build_app_compatibility(supported_workspace_modes=workspace_modes),
            entrypoints=build_app_entrypoints(hooks=hooks) if hooks is not None else None,
        ),
    )
    write_app_contract_file(app_root, parsed)


def _make_app_store() -> AppDocumentStore:
    return AppDocumentStore(
        AppCollections(
            app_sources=FakeCollection(),
            workspace_local_app_projects=FakeCollection(),
            workspace_app_bindings=FakeCollection(),
            workspace_app_sidecar_quarantines=FakeCollection(),
            workspace_app_dependency_selections=FakeCollection(),
        )
    )


def _make_workspace_store() -> WorkspaceDocumentStore:
    return WorkspaceDocumentStore(
        WorkspaceCollections(
            workspaces=FakeCollection(),
            memberships=FakeCollection(),
            governance=FakeCollection(),
            quotas=FakeCollection(),
            active_workspace_selections=FakeCollection(),
        )
    )


if __name__ == "__main__":
    unittest.main()
