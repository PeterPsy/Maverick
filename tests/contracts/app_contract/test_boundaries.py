"""Split tests from app hosting helper module."""

from __future__ import annotations

import ast
from pathlib import Path

from core.apps import contract_builders, contract_parser, contract_serializer, contract_validation
from core.apps.contract_common import APP_CONTRACT_FILENAME, APP_ID_PATTERN, CURRENT_APP_CONTRACT_VERSION
from tests.support.app_hosting import *


class TestAppContractBoundaries(AppHostingTestBase):
    """Focused test slice."""

    def test_contract_constants_are_owned_by_contract_common(self) -> None:
        self.assertIs(contract_validation.APP_ID_PATTERN, APP_ID_PATTERN)
        self.assertEqual(contract_builders.CURRENT_APP_CONTRACT_VERSION, CURRENT_APP_CONTRACT_VERSION)
        self.assertEqual(contract_parser.app_contract_path(Path("/tmp/app")).name, APP_CONTRACT_FILENAME)
        self.assertEqual(contract_serializer.app_contract_path(Path("/tmp/app")).name, APP_CONTRACT_FILENAME)

        repo_root = Path(__file__).resolve().parents[3]
        duplicate_assignments = []
        for path in sorted((repo_root / "core" / "apps").glob("contract_*.py")):
            if path.name == "contract_common.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id in {
                            "CURRENT_APP_CONTRACT_VERSION",
                            "APP_CONTRACT_FILENAME",
                            "APP_ID_PATTERN",
                        }:
                            duplicate_assignments.append(f"{path.relative_to(repo_root)}:{target.id}")

        self.assertEqual(duplicate_assignments, [])

    def test_compatibility_checks_reject_invalid_contract_and_workspace_mode(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            bad_root = repo_root / "apps" / "_bundles" / "unsafe" / "1.0.0"
            good_root = repo_root / "apps" / "_bundles" / "operator-tools" / "1.0.0"
            self.write_contract(
                bad_root,
                app_id="unsafe",
                name="Unsafe",
                publisher="vendor",
                contract=build_app_contract(
                    compatibility=build_app_compatibility(contract_version="2.0"),
                ),
            )
            self.write_contract(
                good_root,
                app_id="operator-tools",
                name="Operator Tools",
                publisher="vendor",
                contract=build_app_contract(
                    compatibility=build_app_compatibility(supported_workspace_modes=["full-access"]),
                ),
            )
            bad_contract = register_app_source_from_contract(
                store,
                source_kind="external_bundle",
                source_path=str(bad_root),
                now=now,
            )
            full_access_only = register_app_source_from_contract(
                store,
                source_kind="external_bundle",
                source_path=str(good_root),
                now=now,
            )
            with self.assertRaises(AppCompatibilityError):
                install_store_app(store, source_id=bad_contract.source_id, workspace_id="default", start_path=repo_root, now=now)
            with self.assertRaises(AppCompatibilityError):
                install_store_app(store, source_id=full_access_only.source_id, workspace_id="acme", start_path=repo_root, now=now)
            binding = install_store_app(store, source_id=full_access_only.source_id, workspace_id="default", start_path=repo_root, now=now)
            self.assertEqual(binding.app_id, "operator-tools")

    def test_trusted_bundle_must_live_under_installation_managed_root(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            rogue_bundle = repo_root / "workspaces" / "default" / "apps" / "rogue"
            self.write_contract(rogue_bundle, app_id="rogue", name="Rogue", publisher="vendor")
            source = register_app_source_from_contract(
                store,
                source_kind="external_bundle",
                source_path=str(rogue_bundle),
                now=now,
            )

            with self.assertRaises(AppLifecycleError):
                install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)

    def test_register_app_source_rejects_invalid_source_kind(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "bad-kind"
            self.write_contract(app_root, app_id="bad-kind")

            with self.assertRaises(AppLifecycleError):
                register_app_source_from_contract(
                    store,
                    source_kind="workspace_local_project",
                    source_path=str(app_root),
                    now=now,
                )
