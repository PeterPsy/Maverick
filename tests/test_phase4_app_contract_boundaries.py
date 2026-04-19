"""Split tests from tests/test_phase4_app_hosting.py."""

from __future__ import annotations

from tests.phase4_app_hosting_helpers import *


class TestPhase4AppContractBoundaries(Phase4AppHostingBase):
    """Focused test slice."""

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
