from __future__ import annotations

import copy
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
MANIFEST_PATH = SERVICE_ROOT / "opendesign_bundle.json"
ACCEPTANCE_PATH = SERVICE_ROOT / "opendesign_oci_acceptance_0_16_1.json"


def _load_module(name: str, path: Path):
    sys.path.insert(0, str(SERVICE_ROOT))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class OpenDesignOciImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = _load_module("opendesign_artifact", SERVICE_ROOT / "opendesign_artifact.py")
        cls.registry = _load_module("opendesign_oci_registry", SERVICE_ROOT / "opendesign_oci_registry.py")
        cls.layout = _load_module("opendesign_oci_layout", SERVICE_ROOT / "opendesign_oci_layout.py")
        cls.boundary = _load_module("opendesign_oci_patch", SERVICE_ROOT / "opendesign_oci_patch.py")
        cls.stage = _load_module("opendesign_oci_stage", SERVICE_ROOT / "opendesign_oci_stage.py")
        cls.importer = _load_module("import_opendesign_oci", SERVICE_ROOT / "import_opendesign_oci.py")

    def setUp(self) -> None:
        self.manifest = self.artifact.read_bundle_manifest(MANIFEST_PATH)

    def test_manifest_pins_complete_oci_chain_and_source_fallback_is_explicit(self) -> None:
        self.artifact.validate_bundle_manifest(self.manifest, require_artifact_digest=False)
        distribution = self.manifest["distribution"]
        self.assertEqual(distribution["primary"], "oci_import")
        self.assertEqual(distribution["index"]["digest"], "sha256:eb1c9d55532ffd2088a4a71951cffd273dff65e96e077bcef8c8bac3a6e1f1a1")
        self.assertEqual(distribution["manifest"]["digest"], distribution["attestation"]["subject_manifest_digest"])
        self.assertEqual(len(distribution["layers"]), 16)
        self.assertEqual(self.manifest["fallback_build"]["patch_series"], "patches/series.json")
        self.assertNotIn("build", self.manifest)

    def test_manifest_rejects_mutated_digest_platform_media_type_and_labels(self) -> None:
        cases = []
        mutated = copy.deepcopy(self.manifest)
        mutated["distribution"]["index"]["digest"] = "sha256:invalid"
        cases.append(mutated)
        mutated = copy.deepcopy(self.manifest)
        mutated["distribution"]["platform"] = {"os": "linux", "architecture": "arm64"}
        cases.append(mutated)
        mutated = copy.deepcopy(self.manifest)
        mutated["distribution"]["layers"][0]["media_type"] = "application/octet-stream"
        cases.append(mutated)
        mutated = copy.deepcopy(self.manifest)
        mutated["distribution"]["expected_revision"] = "0" * 40
        cases.append(mutated)
        for candidate in cases:
            with self.subTest(candidate=candidate["distribution"]):
                with self.assertRaises(self.artifact.ArtifactError):
                    self.artifact.validate_bundle_manifest(candidate, require_artifact_digest=False)

    def test_registry_metadata_checks_config_and_slsa_subject(self) -> None:
        distribution = self.manifest["distribution"]
        config = {
            "config": {
                "Labels": {
                    "org.opencontainers.image.revision": distribution["expected_revision"],
                    "org.opencontainers.image.version": distribution["expected_version"],
                },
                "Entrypoint": ["/sbin/tini", "--"],
                "Cmd": ["node", "apps/daemon/dist/cli.js", "--no-open"],
            }
        }
        self.registry._verify_config(config, distribution)
        bad_config = copy.deepcopy(config)
        bad_config["config"]["Labels"]["org.opencontainers.image.version"] = "latest"
        with self.assertRaisesRegex(self.registry.OciRegistryError, "version label"):
            self.registry._verify_config(bad_config, distribution)

        statement = {
            "_type": "https://in-toto.io/Statement/v1",
            "predicateType": "https://slsa.dev/provenance/v1",
            "subject": [{"digest": {"sha256": distribution["manifest"]["digest"][7:]}}],
            "predicate": {
                "buildDefinition": {
                    "externalParameters": {
                        "request": {
                            "args": {
                                "label:org.opencontainers.image.revision": distribution["expected_revision"]
                            }
                        }
                    }
                }
            },
        }
        self.registry._verify_attestation(statement, distribution)
        statement["subject"][0]["digest"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(self.registry.OciRegistryError, "subject"):
            self.registry._verify_attestation(statement, distribution)

    def test_registry_rejects_corrupted_descriptor_bytes(self) -> None:
        payload = b"pinned"
        descriptor = {
            "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        }
        self.registry._verify_bytes(payload, descriptor)
        with self.assertRaisesRegex(self.registry.OciRegistryError, "do not match"):
            self.registry._verify_bytes(payload + b"!", descriptor)

    def test_safe_layers_apply_whiteouts_without_following_links(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-oci-layout-") as temporary:
            root = Path(temporary)
            first = root / "first.tar.gz"
            second = root / "second.tar.gz"
            _write_layer(first, [("file", "data/old.txt", b"old"), ("file", "data/keep.txt", b"keep")])
            _write_layer(
                second,
                [
                    ("file", "data/.wh.old.txt", b""),
                    ("file", "data/new.txt", b"new"),
                ],
            )
            rootfs = root / "rootfs"
            self.layout.apply_layers((first, second), rootfs)
            self.assertFalse((rootfs / "data/old.txt").exists())
            self.assertEqual((rootfs / "data/keep.txt").read_bytes(), b"keep")
            self.assertEqual((rootfs / "data/new.txt").read_bytes(), b"new")

    def test_malicious_layer_paths_links_whiteouts_and_special_files_fail_closed(self) -> None:
        fixtures = [
            [("file", "../escape", b"bad")],
            [("symlink", "pivot", "../outside"), ("file", "pivot/file", b"bad")],
            [("hardlink", "copy", "/etc/passwd")],
            [("file", "safe/.wh...", b"")],
            [("fifo", "pipe", b"")],
        ]
        for index, members in enumerate(fixtures):
            with self.subTest(index=index), tempfile.TemporaryDirectory(prefix="maverick-od-oci-hostile-") as temporary:
                root = Path(temporary)
                layer = root / "hostile.tar.gz"
                _write_layer(layer, members)
                with self.assertRaises(self.layout.OciLayoutError):
                    self.layout.apply_layers((layer,), root / "rootfs")
                self.assertFalse((root / "escape").exists())

    def test_truncated_layer_fails_and_removes_incomplete_rootfs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-oci-truncated-") as temporary:
            root = Path(temporary)
            layer = root / "truncated.tar.gz"
            layer.write_bytes(b"not-a-layer")
            rootfs = root / "rootfs"
            with self.assertRaises(self.layout.OciLayoutError):
                self.layout.apply_layers((layer,), rootfs)
            self.assertFalse(rootfs.exists())

    def test_compiled_boundary_patch_requires_single_exact_preimage(self) -> None:
        source = (
            self.boundary._STATIC_DIR_DECLARATION
            + b"static-middle\n"
            + self.boundary._START_SERVER_HOST
            + self.boundary._TOKEN_DECLARATIONS
            + b"middle\n"
            + self.boundary._LOOPBACK_BYPASS
            + self.boundary._STATIC_MOUNT
            + self.boundary._READY_ROUTE
            + self.boundary._BUNDLED_CATALOG_DECLARATION
            + self.boundary._BUNDLED_CATALOG_START
            + b"catalog-middle\n"
            + self.boundary._BUNDLED_CATALOG_ASSIGNMENT_START
            + self.boundary._BUNDLED_CATALOG_ASSIGNMENT_END
            + b"catalog-seed-middle\n"
            + self.boundary._BUNDLED_CATALOG_END
            + self.boundary._DAEMON_BACKGROUND_CLEANUP
            + self.boundary._DAEMON_SHUTDOWN_START
            + self.boundary._DAEMON_LISTEN_COMMIT
        )
        with tempfile.TemporaryDirectory(prefix="maverick-od-oci-patch-") as temporary:
            stage = Path(temporary)
            target = stage / "app/apps/daemon/dist/server.js"
            target.parent.mkdir(parents=True)
            target.write_bytes(source)
            manifest = copy.deepcopy(self.manifest)
            manifest["boundary_patch"]["pre_sha256"] = hashlib.sha256(source).hexdigest()
            manifest["boundary_patch"]["post_sha256"] = None
            evidence = self.boundary.apply_boundary_patch(stage, manifest)
            self.assertEqual(evidence["path"], "app/apps/daemon/dist/server.js")
            self.assertIn(b"!requireApiTokenOnLoopback", target.read_bytes())
            self.assertIn(b"OD_STATIC_REGISTRY_ROOT", target.read_bytes())
            self.assertIn(b"/api/maverick-ready", target.read_bytes())
            self.assertIn(b"OD_MAVERICK_DEFER_PLUGIN_CATALOG", target.read_bytes())
            self.assertIn(b"bundledCatalogTimer.unref", target.read_bytes())
            self.assertNotIn("web_patch", evidence)
            with self.assertRaisesRegex(self.boundary.BoundaryPatchError, "preimage"):
                self.boundary.apply_boundary_patch(stage, manifest)

    def test_compiled_startup_patch_is_bounded_and_requires_exact_preimage(self) -> None:
        source = (
            self.boundary._BUNDLED_REGISTRY_IMPORT
            + self.boundary._BUNDLED_WARNINGS_DECLARATION
            + b"middle\n"
            + self.boundary._DIRECT_BUNDLED_REGISTRATION
            + self.boundary._NESTED_BUNDLED_REGISTRATION
            + self.boundary._BUNDLED_REGISTRATION_COMMIT
            + self.boundary._BUNDLED_DIGEST_HELPER_SITE
            + self.boundary._BUNDLED_CONTENT_DIGEST
        )
        with tempfile.TemporaryDirectory(prefix="maverick-od-oci-startup-patch-") as temporary:
            stage = Path(temporary)
            target = stage / "app/apps/daemon/dist/plugins/bundled.js"
            target.parent.mkdir(parents=True)
            target.write_bytes(source)
            manifest = copy.deepcopy(self.manifest)
            manifest["startup_patch"]["pre_sha256"] = hashlib.sha256(source).hexdigest()
            manifest["startup_patch"]["post_sha256"] = None
            evidence = self.boundary.apply_startup_patch(stage, manifest)
            self.assertEqual(evidence["max_concurrency"], 8)
            self.assertEqual(target.read_bytes().count(b"forEachConcurrent(candidates, 8"), 1)
            self.assertEqual(target.read_bytes().count(b"maverick-protected-runtime-v1"), 1)
            self.assertNotIn(b"await registerOne({ folder: tierAbs", target.read_bytes())
            with self.assertRaisesRegex(self.boundary.BoundaryPatchError, "preimage"):
                self.boundary.apply_startup_patch(stage, manifest)

    def test_web_patch_is_a_rebuilt_react_boundary_without_dom_pruning(self) -> None:
        compiled_patch = (SERVICE_ROOT / "opendesign_oci_patch.py").read_text(encoding="utf-8")
        react_patch = (SERVICE_ROOT / "patches/0003-maverick-web-react.patch").read_text(encoding="utf-8")
        self.assertNotIn("MutationObserver", compiled_patch)
        self.assertNotIn("querySelectorAll", compiled_patch)
        for marker in (
            "function MaverickProjectView",
            "maverickHosted ? null",
            "maverick.opendesign.open-settings",
            "maverick.opendesign.settings-closed",
        ):
            self.assertIn(marker, react_patch)
        self.assertEqual(
            self.manifest["web_patch"]["capabilities"],
            [
                "react_hosted_project_view",
                "native_chat_unmounted",
                "native_home_unmounted",
                "native_workspace_tabs_unmounted",
                "native_settings_bridge",
                "maverick_theme",
                "project_navigation_bridge",
            ],
        )

    def test_runtime_command_uses_only_imported_loader_libraries_and_node(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-oci-command-") as temporary:
            root = Path(temporary)
            for relative in (
                "runtime/lib/ld-musl-x86_64.so.1",
                "runtime/bin/node",
                "app/apps/daemon/dist/cli.js",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            (root / "runtime/usr-lib").mkdir()
            command = self.stage.runtime_command(root, self.manifest)
            self.assertEqual(command[0], str(root / "runtime/lib/ld-musl-x86_64.so.1"))
            self.assertEqual(command[3], str(root / "runtime/bin/node"))
            self.assertEqual(command[4:6], ["--input-type=module", "--eval"])
            self.assertIn("enableCompileCache", command[6])
            self.assertEqual(
                command[-2:],
                [(root / "app/apps/daemon/dist/cli.js").as_uri(), "--no-open"],
            )
            self.assertNotEqual(command[3], "node")

    def test_staging_normalization_clears_inherited_setgid_before_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-oci-setgid-") as temporary:
            parent = Path(temporary) / "shared-work"
            parent.mkdir()
            parent.chmod(0o2775)
            staging = parent / "staging"
            staging.mkdir()
            (staging / "runtime").mkdir()

            self.stage._normalize_tree(staging)
            metadata = staging / "maverick"
            metadata.mkdir()

            self.assertEqual(stat.S_IMODE(staging.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((staging / "runtime").stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(metadata.stat().st_mode), 0o755)

    def test_oci_publish_is_idempotent_only_for_identical_verified_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-oci-publish-") as temporary:
            root = Path(temporary)
            source = root / "source.tar.gz"
            destination = root / "published.tar.gz"
            source.write_bytes(b"verified artifact")
            destination.write_bytes(source.read_bytes())
            inode = destination.stat().st_ino

            self.importer._publish_file(source, destination)
            self.assertEqual(destination.stat().st_ino, inode)

            source.write_bytes(b"conflicting artifact")
            with self.assertRaisesRegex(self.importer.OciImportError, "conflicts"):
                self.importer._publish_file(source, destination)
            self.assertEqual(destination.read_bytes(), b"verified artifact")

    def test_oci_derivation_must_match_existing_canonical_pins(self) -> None:
        asset = self.manifest["artifact"]["assets"]["linux-x86_64"]
        declared = {
            "size_bytes": asset["size_bytes"],
            **{
                digest_field: asset[digest_field]
                for digest_field in self.artifact.ARTIFACT_DIGEST_FIELDS.values()
            },
        }
        self.importer._assert_declared_pins(self.manifest, asset=asset, pins=declared)
        mismatched = dict(declared)
        mismatched["sha256"] = "0" * 64
        with self.assertRaisesRegex(self.importer.OciImportError, "canonical artifact pins"):
            self.importer._assert_declared_pins(self.manifest, asset=asset, pins=mismatched)

    def test_primary_import_has_no_docker_socket_or_embedded_web_builder(self) -> None:
        sources = "\n".join(
            (SERVICE_ROOT / name).read_text(encoding="utf-8")
            for name in (
                "import_opendesign_oci.py",
                "opendesign_oci_registry.py",
                "opendesign_oci_layout.py",
                "opendesign_oci_stage.py",
            )
        )
        for forbidden in ("docker run", "/var/run/docker.sock"):
            self.assertNotIn(forbidden, sources.lower())
        self.assertNotIn("build_and_overlay_web", sources)
        self.assertIn("runtime closure must not contain embedded web output", sources)

    def test_real_acceptance_record_matches_canonical_manifest(self) -> None:
        acceptance = json.loads(ACCEPTANCE_PATH.read_text(encoding="utf-8"))
        distribution = self.manifest["distribution"]
        asset = self.manifest["artifact"]["assets"]["linux-x86_64"]
        self.assertEqual(acceptance["schema_version"], "1")
        self.assertEqual(acceptance["oci"]["index_digest"], distribution["index"]["digest"])
        self.assertEqual(acceptance["oci"]["manifest_digest"], distribution["manifest"]["digest"])
        for digest_field in self.artifact.ARTIFACT_DIGEST_FIELDS.values():
            self.assertEqual(acceptance["artifact"][digest_field], asset[digest_field])
        self.assertEqual(acceptance["artifact"]["size_bytes"], asset["size_bytes"])
        for field in ("path", "pre_sha256", "post_sha256"):
            self.assertEqual(acceptance["boundary_patch"][field], self.manifest["boundary_patch"][field])
        for field in ("path", "pre_sha256", "post_sha256", "max_concurrency"):
            self.assertEqual(acceptance["startup_patch"][field], self.manifest["startup_patch"][field])
        self.assertEqual(
            acceptance["runtime_smoke"]["web_overlay_sha256"],
            acceptance["web_overlay"]["web_overlay_sha256"],
        )
        self.assertFalse(acceptance["runtime_smoke"]["embedded_static_web"])
        web_trust = json.loads((SERVICE_ROOT / "opendesign_web_trust.json").read_text(encoding="utf-8"))
        self.assertEqual(
            acceptance["web_overlay"]["trust_root_public_key_sha256"],
            web_trust["public_key_sha256"],
        )
        self.assertEqual(acceptance["import"]["independent_derivations"], 2)
        self.assertTrue(acceptance["import"]["reproducible"])
        self.assertTrue(acceptance["runtime_smoke"]["ready"])
        self.assertTrue(acceptance["runtime_smoke"]["maverick_ready"])
        self.assertEqual(acceptance["runtime_smoke"]["sqlite_integrity"], "ok")
        self.assertEqual(
            acceptance["runtime_smoke"]["bearer"],
            {"correct": 200, "missing": 401, "wrong": 401},
        )
        self.assertFalse(acceptance["workspace_data_migrated"])


def _write_layer(path: Path, members: list[tuple[str, str, object]]) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        for kind, name, payload in members:
            member = tarfile.TarInfo(name)
            member.mtime = 0
            if kind == "file":
                content = bytes(payload)
                member.size = len(content)
                member.mode = 0o644
                archive.addfile(member, BytesIO(content))
            elif kind == "symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = str(payload)
                archive.addfile(member)
            elif kind == "hardlink":
                member.type = tarfile.LNKTYPE
                member.linkname = str(payload)
                archive.addfile(member)
            elif kind == "fifo":
                member.type = tarfile.FIFOTYPE
                archive.addfile(member)
            else:
                raise AssertionError(kind)


if __name__ == "__main__":
    unittest.main()
