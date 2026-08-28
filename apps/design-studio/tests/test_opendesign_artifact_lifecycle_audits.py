"""Proofs that lifecycle transitions cannot substitute receipt-fast checks for audits."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_artifact_operations import (  # noqa: E402
    RequiredArtifacts,
    _repair,
    _repair_operation_lock,
)
from opendesign_artifact_store import (  # noqa: E402
    ArtifactStoreError,
    OpenDesignArtifactStore,
    StoredArtifact,
)
from opendesign_generation_model import GenerationControl, LaunchSelection  # noqa: E402
import opendesign_launcher  # noqa: E402
from opendesign_migration_oci_runtime import OciMigrationRuntime  # noqa: E402
from opendesign_release_activation import activate_protected_release  # noqa: E402
from opendesign_runtime import protected_activation_inventory  # noqa: E402


RUNTIME_ACTIVE = "a" * 64
RUNTIME_ROLLBACK = "b" * 64
WEB_ACTIVE = "c" * 64
WEB_ROLLBACK = "d" * 64
WEB_RUNTIME_TARGET = "2" * 64


def _runtime(digest: str) -> StoredArtifact:
    return StoredArtifact(
        "runtime",
        digest,
        Path("/store/runtime") / digest / "content",
        Path("/store/runtime") / digest,
        {
            "opendesign_version": "0.16.1",
            "upstream_commit": "e" * 40,
            "source_file_manifest_sha256": "f" * 64,
            "compatible_runtime_artifact_sha256": [digest],
        },
    )


def _web(digest: str, runtime_digest: str) -> StoredArtifact:
    return StoredArtifact(
        "web",
        digest,
        Path("/store/web") / digest / "content",
        Path("/store/web") / digest,
        {
            "opendesign_version": "0.16.1",
            "upstream_commit": "e" * 40,
            "source_file_manifest_sha256": "1" * 64,
            "compatible_runtime_artifact_sha256": [runtime_digest],
        },
    )


class OpenDesignArtifactLifecycleAuditTests(unittest.TestCase):
    def test_overlapping_governed_repairs_fail_without_waiting_or_mutating(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-repair-lock-") as temp:
            root = Path(temp)
            (root / ".locks").mkdir()
            store = SimpleNamespace(root=root)
            with _repair_operation_lock(store):
                with self.assertRaises(ArtifactStoreError) as raised:
                    with _repair_operation_lock(store):
                        self.fail("overlapping repair unexpectedly acquired the lock")

        self.assertEqual(raised.exception.code, "artifact_repairing")
        self.assertEqual(raised.exception.phase, "repair_lock")

    def test_release_activation_audits_candidate_and_active_rollback_pair(self) -> None:
        active = LaunchSelection(RUNTIME_ACTIVE, WEB_ACTIVE, "0.16.1", "gen_active")
        target = LaunchSelection(RUNTIME_ROLLBACK, WEB_ROLLBACK, "0.16.1", "gen_active")
        control = GenerationControl(
            active,
            None,
            None,
            None,
            None,
            "2026-08-26T00:00:00Z",
        )
        committed = GenerationControl(
            target,
            None,
            None,
            None,
            None,
            "2026-08-26T00:00:01Z",
            previous_runtime=active,
        )
        store = Mock(spec=OpenDesignArtifactStore)

        def audited_runtime(_store, digest, **_kwargs):
            return _runtime(digest)

        def audited_web(_store, digest, *, runtime_artifact_sha256, **_kwargs):
            return _web(digest, runtime_artifact_sha256)

        with (
            patch(
                "opendesign_release_activation.load_generation_control_metadata",
                return_value=control,
            ),
            patch(
                "opendesign_release_activation.selected_asset",
                return_value={
                    "sha256": RUNTIME_ROLLBACK,
                    "file_manifest_sha256": "f" * 64,
                },
            ),
            patch(
                "opendesign_release_activation.fully_audited_runtime",
                side_effect=audited_runtime,
            ) as runtime_audit,
            patch(
                "opendesign_release_activation.fully_audited_web_overlay",
                side_effect=audited_web,
            ) as web_audit,
            patch(
                "opendesign_release_activation.runtime_activation_recovery_state",
                return_value="none",
            ),
            patch(
                "opendesign_release_activation.activate_runtime_binding",
                return_value=SimpleNamespace(
                    control=committed,
                    rolled_back=False,
                    activated=True,
                ),
            ),
        ):
            result = activate_protected_release(
                Path("/data/opendesign"),
                store=store,
                manifest={
                    "upstream": {
                        "release_version": "0.16.1",
                        "commit": "e" * 40,
                    },
                },
                target_web_overlay_sha256=WEB_ROLLBACK,
                restart_sidecars=lambda: {"ready": True},
            )

        self.assertEqual(result.outcome.control.active, target)
        self.assertEqual(
            [item.args[1] for item in runtime_audit.call_args_list],
            [RUNTIME_ROLLBACK, RUNTIME_ACTIVE],
        )
        self.assertEqual(
            [item.args[1] for item in web_audit.call_args_list],
            [WEB_ROLLBACK, WEB_ACTIVE],
        )

    def test_protected_activation_inventory_full_audits_every_control_reference(self) -> None:
        active = LaunchSelection(RUNTIME_ACTIVE, WEB_ACTIVE, "0.16.1", "gen_active")
        rollback = LaunchSelection(RUNTIME_ROLLBACK, WEB_ROLLBACK, "0.16.1", "gen_active")
        control = GenerationControl(
            active,
            None,
            None,
            None,
            None,
            "2026-08-26T00:00:00Z",
            previous_runtime=rollback,
        )
        store = Mock(spec=OpenDesignArtifactStore)
        store.fast_runtime.side_effect = lambda digest, **_kwargs: _runtime(digest)
        store.fast_web_overlay.side_effect = (
            lambda digest, *, runtime_artifact_sha256: _web(digest, runtime_artifact_sha256)
        )

        with (
            patch("opendesign_runtime.load_generation_control_metadata", return_value=control),
            patch("opendesign_runtime.load_generation_control", return_value=control),
        ):
            observed, artifacts, overlays = protected_activation_inventory(
                store=store,
                generation_root=Path("/data/opendesign"),
            )

        self.assertEqual(observed, control)
        self.assertEqual(set(artifacts), {RUNTIME_ACTIVE, RUNTIME_ROLLBACK})
        self.assertEqual(set(overlays), {WEB_ACTIVE, WEB_ROLLBACK})
        audited = {(item.args[0], item.args[1]) for item in store.full_audit.call_args_list}
        self.assertEqual(
            audited,
            {
                ("runtime", RUNTIME_ACTIVE),
                ("runtime", RUNTIME_ROLLBACK),
                ("web", WEB_ACTIVE),
                ("web", WEB_ROLLBACK),
            },
        )

    def test_protected_activation_inventory_includes_retained_runtime_journal_target(self) -> None:
        active = LaunchSelection(RUNTIME_ACTIVE, WEB_ACTIVE, "0.16.1", "gen_active")
        rollback = LaunchSelection(RUNTIME_ROLLBACK, WEB_ROLLBACK, "0.16.1", "gen_active")
        runtime_target = LaunchSelection(
            RUNTIME_ACTIVE,
            WEB_RUNTIME_TARGET,
            "0.16.1",
            "gen_active",
        )
        control = GenerationControl(
            active,
            None,
            None,
            None,
            None,
            "2026-08-26T00:00:00Z",
            previous_runtime=rollback,
            runtime_activation_id="runtime_release_retained",
        )
        journal = SimpleNamespace(source=rollback, target=runtime_target)
        store = Mock(spec=OpenDesignArtifactStore)
        store.fast_runtime.side_effect = lambda digest, **_kwargs: _runtime(digest)
        store.fast_web_overlay.side_effect = (
            lambda digest, *, runtime_artifact_sha256: _web(digest, runtime_artifact_sha256)
        )

        with (
            patch("opendesign_runtime.load_generation_control_metadata", return_value=control),
            patch(
                "opendesign_runtime.load_runtime_activation_journal_metadata",
                return_value=journal,
            ) as load_journal,
            patch("opendesign_runtime.load_generation_control", return_value=control),
        ):
            observed, artifacts, overlays = protected_activation_inventory(
                store=store,
                generation_root=Path("/data/opendesign"),
            )

        self.assertEqual(observed, control)
        load_journal.assert_called_once_with(
            Path("/data/opendesign"),
            "runtime_release_retained",
        )
        self.assertEqual(set(artifacts), {RUNTIME_ACTIVE, RUNTIME_ROLLBACK})
        self.assertEqual(
            set(overlays),
            {WEB_ACTIVE, WEB_ROLLBACK, WEB_RUNTIME_TARGET},
        )
        audited = {(item.args[0], item.args[1]) for item in store.full_audit.call_args_list}
        self.assertEqual(
            audited,
            {
                ("runtime", RUNTIME_ACTIVE),
                ("runtime", RUNTIME_ROLLBACK),
                ("web", WEB_ACTIVE),
                ("web", WEB_ROLLBACK),
                ("web", WEB_RUNTIME_TARGET),
            },
        )

    def test_launcher_finalization_verifies_retained_journal_selections(self) -> None:
        active = LaunchSelection(RUNTIME_ACTIVE, WEB_ACTIVE, "0.16.1", "gen_active")
        rollback = LaunchSelection(RUNTIME_ROLLBACK, WEB_ROLLBACK, "0.16.1", "gen_active")
        runtime_target = LaunchSelection(
            RUNTIME_ACTIVE,
            WEB_RUNTIME_TARGET,
            "0.16.1",
            "gen_active",
        )
        control = SimpleNamespace(
            web_activation_id="web_release_current",
            runtime_activation_id="runtime_release_retained",
        )
        binding = SimpleNamespace(
            active=active,
            bundle=SimpleNamespace(opendesign_version="0.16.1"),
            control=control,
        )
        store = Mock(spec=OpenDesignArtifactStore)
        store.fast_runtime.side_effect = lambda digest, **_kwargs: _runtime(digest)
        store.fast_web_overlay.side_effect = (
            lambda digest, *, runtime_artifact_sha256: _web(digest, runtime_artifact_sha256)
        )
        readiness = {"ready": True, "service_count": 1}

        with (
            patch("opendesign_launcher.OpenDesignArtifactStore", return_value=store),
            patch(
                "opendesign_launcher.activation_inventory_selections",
                return_value=(active, rollback, runtime_target),
            ) as inventory,
            patch(
                "opendesign_launcher.finalize_runtime_activation_after_verified_sidecar_start"
            ) as finalize_runtime,
            patch(
                "opendesign_launcher.finalize_web_activation_after_verified_sidecar_start"
            ) as finalize_web,
        ):
            opendesign_launcher._finalize_pending_activations(
                Path("/data/opendesign"),
                binding=binding,
                web_registry_root=Path("/store/web"),
                readiness=readiness,
            )

        inventory.assert_called_once_with(control, Path("/data/opendesign"))
        runtime_kwargs = finalize_runtime.call_args.kwargs
        web_kwargs = finalize_web.call_args.kwargs
        self.assertEqual(
            set(runtime_kwargs["verified_artifacts"]),
            {RUNTIME_ACTIVE, RUNTIME_ROLLBACK},
        )
        self.assertEqual(
            set(runtime_kwargs["verified_overlays"]),
            {WEB_ACTIVE, WEB_ROLLBACK, WEB_RUNTIME_TARGET},
        )
        self.assertEqual(web_kwargs["verified_artifacts"], runtime_kwargs["verified_artifacts"])
        self.assertEqual(web_kwargs["verified_overlays"], runtime_kwargs["verified_overlays"])

    def test_provision_and_repair_audit_fast_valid_reused_packages(self) -> None:
        required = RequiredArtifacts(
            current_runtime=RUNTIME_ACTIVE,
            active_runtime=RUNTIME_ACTIVE,
            rollback_runtime=RUNTIME_ROLLBACK,
            active_web=WEB_ACTIVE,
            optional_runtime=(),
            web_overlays=(WEB_ACTIVE, WEB_ROLLBACK),
            fresh_web_overlay=WEB_ACTIVE,
        )
        manifest = {
            "upstream": {"release_version": "0.16.1", "commit": "e" * 40},
        }
        runtime_sources = SimpleNamespace(
            source_for_digest=lambda digest: SimpleNamespace(
                manifest=manifest,
                artifact_sha256=digest,
            ),
        )
        store = Mock(spec=OpenDesignArtifactStore)
        store.fast_web_overlay.return_value = _web(WEB_ACTIVE, RUNTIME_ACTIVE)

        def audited_runtime(_store, digest, **_kwargs):
            return _runtime(digest)

        def audited_web(_store, digest, **_kwargs):
            return _web(digest, RUNTIME_ACTIVE)

        with (
            patch(
                "opendesign_artifact_operations.selected_asset",
                return_value={
                    "sha256": RUNTIME_ACTIVE,
                    "file_manifest_sha256": "f" * 64,
                },
            ),
            patch(
                "opendesign_artifact_operations.fully_audited_runtime",
                side_effect=audited_runtime,
            ) as runtime_audit,
            patch(
                "opendesign_artifact_operations.fully_audited_web_overlay_for_any_runtime",
                side_effect=audited_web,
            ) as web_audit,
            patch("opendesign_artifact_operations._known_invalid_identity", return_value=None),
            patch("opendesign_artifact_operations._bootstrap_fresh_generation", return_value=False),
        ):
            result = _repair(
                store,
                required=required,
                runtime_sources=runtime_sources,
                data_root=Path("/data/design-studio"),
            )

        self.assertFalse(result["runtime_repaired"])
        self.assertEqual(
            [item.args[1] for item in runtime_audit.call_args_list],
            [RUNTIME_ACTIVE, RUNTIME_ROLLBACK],
        )
        self.assertEqual(
            [item.args[1] for item in web_audit.call_args_list],
            [WEB_ACTIVE, WEB_ROLLBACK],
        )
        store.publish_runtime.assert_not_called()
        store.publish_web_overlay.assert_not_called()

    def test_controlled_migration_audits_protected_runtime_and_overlay(self) -> None:
        manifest = {
            "upstream": {
                "release_version": "0.16.1",
                "commit": "e" * 40,
            },
        }
        with tempfile.TemporaryDirectory(prefix="maverick-audit-migration-") as temp:
            root = Path(temp)
            (root / "web" / WEB_ACTIVE).mkdir(parents=True)
            store = Mock(spec=OpenDesignArtifactStore)
            store.root = root
            runtime = _runtime(RUNTIME_ACTIVE)
            web = _web(WEB_ACTIVE, RUNTIME_ACTIVE)
            trust_contract = root / "web-trust.json"
            with (
                patch(
                    "opendesign_migration_oci_runtime.OpenDesignArtifactStore",
                    return_value=store,
                ),
                patch(
                    "opendesign_migration_oci_runtime.fully_audited_runtime",
                    return_value=runtime,
                ) as runtime_audit,
                patch(
                    "opendesign_migration_oci_runtime.fully_audited_web_overlay",
                    return_value=web,
                ) as web_audit,
            ):
                runtime_root, web_root, bundles, overlays = (
                    OciMigrationRuntime._protected_store_inventory(
                        SimpleNamespace(manifest=manifest),
                        root,
                        selected={
                            "sha256": RUNTIME_ACTIVE,
                            "file_manifest_sha256": "f" * 64,
                        },
                        web_trust_contract=trust_contract,
                    )
                )

        self.assertEqual(runtime_root, root / "runtime")
        self.assertEqual(web_root, root / "web")
        self.assertEqual(set(bundles), {RUNTIME_ACTIVE})
        self.assertEqual(set(overlays), {WEB_ACTIVE})
        runtime_audit.assert_called_once_with(
            store,
            RUNTIME_ACTIVE,
            file_manifest_sha256="f" * 64,
            opendesign_version="0.16.1",
            upstream_commit="e" * 40,
        )
        web_audit.assert_called_once_with(
            store,
            WEB_ACTIVE,
            runtime_artifact_sha256=RUNTIME_ACTIVE,
            trust_contract=trust_contract,
        )


if __name__ == "__main__":
    unittest.main()
