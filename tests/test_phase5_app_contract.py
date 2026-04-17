"""Tests for canonical app contract parsing and Phase 5 contract support."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.apps.contracts import (
    app_contract_path,
    build_app_capabilities,
    build_app_compatibility,
    build_app_contract,
    build_app_entrypoints,
    build_app_hook_timeouts,
    build_app_lifecycle,
    build_app_storage,
    build_parsed_app_contract,
    parse_app_contract_file,
    write_app_contract_file,
)
from core.apps.errors import AppContractValidationError
from core.apps.lifecycle import run_lifecycle_hook


class Phase5AppContractTestCase(unittest.TestCase):
    """Verify canonical contract-file parsing, validation, and timeout-backed hook execution."""

    def test_parse_contract_file_supports_storage_capabilities_and_lifecycle(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "restaurant-manager"
            (app_root / "backend" / "mcp").mkdir(parents=True, exist_ok=True)
            (app_root / "backend" / "cli").mkdir(parents=True, exist_ok=True)
            (app_root / "backend" / "skills").mkdir(parents=True, exist_ok=True)
            (app_root / "backend" / "lifecycle").mkdir(parents=True, exist_ok=True)
            (app_root / "backend" / "mcp" / "server.py").write_text("print('mcp')\n", encoding="utf-8")
            (app_root / "backend" / "cli" / "app_cli.py").write_text("print('cli')\n", encoding="utf-8")
            (app_root / "backend" / "lifecycle" / "install.py").write_text("print('install')\n", encoding="utf-8")
            (app_root / "backend" / "lifecycle" / "health.py").write_text("print('health')\n", encoding="utf-8")
            parsed = build_parsed_app_contract(
                app_id="restaurant_manager",
                name="Restaurant Manager",
                version="1.2.0",
                description="Manage rooms and tables.",
                publisher="third-party-dev",
                contract=build_app_contract(
                    compatibility=build_app_compatibility(supported_workspace_modes=["sandbox", "full-access"]),
                    storage=build_app_storage(
                        storage_kind="sqlite",
                        primary_paths=["data/restaurant-manager/app.db"],
                        indices_kind="embedded",
                        supports_export=True,
                        supports_import=True,
                        supports_migrations=True,
                    ),
                    capabilities=build_app_capabilities(
                        mcp_tools=["tables.list"],
                        cli_commands=["tables"],
                        skills=["restaurant-operations"],
                        views=["floor_map"],
                    ),
                    lifecycle=build_app_lifecycle(
                        migrate=True,
                        export=True,
                        import_data=True,
                        validate_after_import=True,
                        repair_after_import=True,
                        health_check=True,
                    ),
                    entrypoints=build_app_entrypoints(
                        mcp="backend/mcp/server.py",
                        cli="backend/cli/app_cli.py",
                        skills_root="backend/skills",
                        hooks={
                            "install": "backend/lifecycle/install.py",
                            "health_check": "backend/lifecycle/health.py",
                        },
                    ),
                    hook_timeouts=build_app_hook_timeouts(
                        upgrade_seconds=180,
                        validate_after_import_seconds=45,
                        repair_after_import_seconds=90,
                    ),
                ),
            )
            write_app_contract_file(app_root, parsed)

            loaded = parse_app_contract_file(app_root)

            self.assertEqual(loaded.app_id, "restaurant-manager")
            self.assertEqual(loaded.contract.storage.storage_kind, "sqlite")
            self.assertEqual(loaded.contract.storage.indices.kind, "embedded")
            self.assertEqual(loaded.contract.capabilities.views, ["floor_map"])
            self.assertTrue(loaded.contract.lifecycle.validate_after_import)
            self.assertTrue(loaded.contract.lifecycle.repair_after_import)
            self.assertEqual(loaded.contract.hook_timeouts.upgrade_seconds, 180)
            self.assertEqual(loaded.contract.hook_timeouts.validate_after_import_seconds, 45)
            self.assertEqual(loaded.contract.entrypoints.skills_root, "backend/skills")

    def test_parse_contract_rejects_storage_outside_owned_namespace(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "unsafe"
            parsed = build_parsed_app_contract(
                app_id="unsafe",
                name="Unsafe",
                version="1.0.0",
                description="Unsafe app.",
                publisher="vendor",
                contract=build_app_contract(
                    storage=build_app_storage(
                        storage_kind="json",
                        primary_paths=["data/other-app/state.json"],
                    )
                ),
            )
            write_app_contract_file(app_root, parsed)

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_parse_contract_rejects_missing_contract_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "missing"
            app_root.mkdir(parents=True, exist_ok=True)

            with self.assertRaises(AppContractValidationError):
                parse_app_contract_file(app_root)

    def test_run_lifecycle_hook_uses_configured_timeout_mapping(self) -> None:
        with TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir) / "apps" / "validator"
            lifecycle_root = app_root / "backend" / "lifecycle"
            lifecycle_root.mkdir(parents=True, exist_ok=True)
            (lifecycle_root / "validate.py").write_text("print('validate')\n", encoding="utf-8")
            parsed = build_parsed_app_contract(
                app_id="validator",
                name="Validator",
                version="1.0.0",
                description="Validator app.",
                publisher="maverick",
                contract=build_app_contract(
                    lifecycle=build_app_lifecycle(validate_after_import=True),
                    entrypoints=build_app_entrypoints(
                        hooks={"validate_after_import": "backend/lifecycle/validate.py"}
                    ),
                ),
            )
            write_app_contract_file(app_root, parsed)
            loaded = parse_app_contract_file(app_root)

            run_lifecycle_hook(app_root, loaded.contract, hook_name="validate_after_import")

            self.assertTrue(app_contract_path(app_root).is_file())


if __name__ == "__main__":
    unittest.main()
