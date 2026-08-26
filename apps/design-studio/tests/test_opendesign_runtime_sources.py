"""Governed current/rollback source-catalog and clean-store provisioning proofs."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from materialize_opendesign import materialize_declared_runtimes  # noqa: E402
from opendesign_artifact import (  # noqa: E402
    ArtifactError,
    selected_asset,
    sha256_file,
    validate_bundle_manifest,
)
from opendesign_artifact_operations import RequiredArtifacts, _repair  # noqa: E402
from opendesign_artifact_store import (  # noqa: E402
    ArtifactStoreError,
    OpenDesignArtifactStore,
    StoredArtifact,
)
from opendesign_runtime_sources import (  # noqa: E402
    RUNTIME_SOURCE_CATALOG_PATH,
    RuntimeArtifactSource,
    RuntimeSourceCatalog,
    load_runtime_source_catalog,
)


CURRENT = "6997f3ab7800c31c027bb1cdd9c9f7634e638b39577c74632eee3b0ce440c5fe"
ROLLBACK = "e56a2144e23941e020bf059385f62627be43324d316de32425abd15d8ddc76ef"
WEB_CURRENT = "76465d47b848595d0144ca93461b898f63a83603d4d7fcf10e4c008474369aad"
WEB_ROLLBACK = "c8f647c0a85575427834400e108a96728fa109f34a6f14e6ea0e1cad19310b74"


def _stored_runtime(digest: str, *, source_manifest: str = "f" * 64) -> StoredArtifact:
    return StoredArtifact(
        "runtime",
        digest,
        Path("/store/runtime") / digest / "content",
        Path("/store/runtime") / digest,
        {
            "opendesign_version": "0.16.1",
            "upstream_commit": "276b4d8e970bc143d7ad060181a89a834e3d9caf",
            "source_file_manifest_sha256": source_manifest,
            "compatible_runtime_artifact_sha256": [digest],
            "store_generation": "1" * 32,
        },
    )


def _stored_web(digest: str, runtime_digest: str) -> StoredArtifact:
    return StoredArtifact(
        "web",
        digest,
        Path("/store/web") / digest / "content",
        Path("/store/web") / digest,
        {
            "opendesign_version": "0.16.1",
            "upstream_commit": "276b4d8e970bc143d7ad060181a89a834e3d9caf",
            "source_file_manifest_sha256": "e" * 64,
            "compatible_runtime_artifact_sha256": [runtime_digest],
        },
    )


class OpenDesignRuntimeSourceTests(unittest.TestCase):
    def test_release_selection_binds_distinct_transactional_source_manifests(self) -> None:
        catalog = load_runtime_source_catalog()
        selection = json.loads(
            (SERVICE_ROOT / "opendesign_release_selection.json").read_text(encoding="utf-8")
        )

        self.assertEqual(selection["schema_version"], "3")
        self.assertEqual(selection["runtime_source_catalog_sha256"], catalog.catalog_sha256)
        self.assertEqual(catalog.catalog_sha256, sha256_file(RUNTIME_SOURCE_CATALOG_PATH))
        self.assertEqual(catalog.by_role["current"].artifact_sha256, CURRENT)
        self.assertEqual(catalog.by_role["rollback"].artifact_sha256, ROLLBACK)
        self.assertEqual(selection["rollback_runtime_artifact_sha256"], ROLLBACK)
        self.assertEqual(selection["rollback_web_overlay_sha256"], WEB_ROLLBACK)
        self.assertEqual(catalog.by_role["rollback"].verifier_profile, "transactional-v1")
        rollback_boundary = catalog.by_role["rollback"].manifest["boundary_patch"]
        self.assertIn("OD_MAVERICK_READY_MARKER", rollback_boundary["required_environment"])
        self.assertIn("OD_MAVERICK_STARTUP_NONCE", rollback_boundary["required_environment"])
        with self.assertRaisesRegex(ArtifactError, "environment is not authorized"):
            validate_bundle_manifest(
                catalog.by_role["rollback"].manifest,
                require_artifact_digest=True,
            )
        with self.assertRaisesRegex(ArtifactError, "environment is not authorized"):
            validate_bundle_manifest(
                catalog.by_role["current"].manifest,
                require_artifact_digest=True,
                verifier_profile="transactional-v1",
            )

    def test_catalog_rejects_a_changed_rollback_manifest_before_source_use(self) -> None:
        with tempfile.TemporaryDirectory(prefix="od-runtime-catalog-") as temporary:
            root = Path(temporary)
            for name in (
                "opendesign_runtime_sources.json",
                "opendesign_bundle.json",
                "opendesign_bundle_rollback_0_16_1.json",
            ):
                shutil.copy2(SERVICE_ROOT / name, root / name)
            load_runtime_source_catalog(root / "opendesign_runtime_sources.json", service_root=root)
            rollback_manifest = root / "opendesign_bundle_rollback_0_16_1.json"
            rollback_manifest.write_bytes(rollback_manifest.read_bytes() + b"\n")
            with self.assertRaisesRegex(ArtifactError, "manifest digest"):
                load_runtime_source_catalog(
                    root / "opendesign_runtime_sources.json",
                    service_root=root,
                )

    def test_new_store_materializer_publishes_and_audits_both_roles(self) -> None:
        catalog = load_runtime_source_catalog()
        with tempfile.TemporaryDirectory(prefix="od-runtime-payload-") as temporary:
            artifact_root = Path(temporary)
            (artifact_root / f"runtime/{ROLLBACK}").mkdir(parents=True)
            store = Mock(spec=OpenDesignArtifactStore)

            def publish(_directory, *, manifest, **_kwargs):
                asset = selected_asset(manifest, require_artifact_digest=True)
                return _stored_runtime(
                    str(asset["sha256"]),
                    source_manifest=str(asset["file_manifest_sha256"]),
                )

            store.publish_runtime.side_effect = publish
            result = materialize_declared_runtimes(
                store,
                artifact_directory=artifact_root,
                catalog=catalog,
            )

        self.assertEqual([item["role"] for item in result], ["current", "rollback"])
        self.assertEqual([item["artifact_sha256"] for item in result], [CURRENT, ROLLBACK])
        self.assertEqual(store.publish_runtime.call_count, 2)
        self.assertEqual(
            [call.args for call in store.full_audit.call_args_list],
            [("runtime", CURRENT), ("runtime", ROLLBACK)],
        )
        rollback_call = store.publish_runtime.call_args_list[1]
        self.assertEqual(rollback_call.args[0], artifact_root / f"runtime/{ROLLBACK}")
        self.assertIsNotNone(rollback_call.kwargs["artifact_verifier"])

    def test_clean_store_provision_repairs_current_and_rollback_from_exact_sources(self) -> None:
        real_catalog = load_runtime_source_catalog()
        current_source = Mock(spec=RuntimeArtifactSource)
        current_source.manifest = real_catalog.by_role["current"].manifest
        current_source.artifact_directory.return_value = Path("/payload/current")
        rollback_source = Mock(spec=RuntimeArtifactSource)
        rollback_source.manifest = real_catalog.by_role["rollback"].manifest
        rollback_source.artifact_directory.return_value = Path("/payload/rollback")
        catalog = RuntimeSourceCatalog(
            catalog_sha256="1" * 64,
            by_role={"current": current_source, "rollback": rollback_source},
            by_digest={CURRENT: current_source, ROLLBACK: rollback_source},
        )
        required = RequiredArtifacts(
            current_runtime=CURRENT,
            active_runtime=CURRENT,
            rollback_runtime=ROLLBACK,
            active_web=WEB_CURRENT,
            optional_runtime=(),
            web_overlays=(WEB_CURRENT, WEB_ROLLBACK),
            fresh_web_overlay=WEB_CURRENT,
        )
        store = Mock(spec=OpenDesignArtifactStore)
        store.package_identity.return_value = None
        store.publish_runtime.side_effect = [
            _stored_runtime(CURRENT),
            _stored_runtime(ROLLBACK),
        ]
        store.fast_web_overlay.return_value = _stored_web(WEB_CURRENT, CURRENT)
        audit_attempts: dict[str, int] = {}

        def runtime_audit(_store, *, digest, source):
            del source
            audit_attempts[digest] = audit_attempts.get(digest, 0) + 1
            if audit_attempts[digest] == 1:
                raise ArtifactStoreError("artifact_missing", "artifact_full_verify", "missing")
            return _stored_runtime(digest)

        with tempfile.TemporaryDirectory(prefix="od-clean-store-") as temporary:
            store.root = Path(temporary)
            with (
                patch(
                    "opendesign_artifact_operations._fully_audited_runtime_source",
                    side_effect=runtime_audit,
                ),
                patch(
                    "opendesign_artifact_operations.fully_audited_web_overlay_for_any_runtime",
                    side_effect=lambda _store, digest, **_kwargs: _stored_web(digest, CURRENT),
                ),
                patch("opendesign_artifact_operations._known_invalid_identity", return_value=None),
                patch("opendesign_artifact_operations._bootstrap_fresh_generation", return_value=False),
            ):
                result = _repair(
                    store,
                    required=required,
                    runtime_sources=catalog,
                    data_root=Path("/data/design-studio"),
                )

        self.assertEqual(result["repaired_runtime_artifacts"], [CURRENT, ROLLBACK])
        self.assertEqual(result["retained_runtime_artifacts"], [CURRENT, ROLLBACK])
        self.assertEqual(store.publish_runtime.call_count, 2)
        current_source.artifact_directory.assert_called_once()
        rollback_source.artifact_directory.assert_called_once()
        self.assertIs(
            store.publish_runtime.call_args_list[0].kwargs["artifact_verifier"],
            current_source.verify_artifact_directory,
        )
        self.assertIs(
            store.publish_runtime.call_args_list[1].kwargs["artifact_verifier"],
            rollback_source.verify_artifact_directory,
        )


if __name__ == "__main__":
    unittest.main()
