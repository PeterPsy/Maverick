from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_archive import write_deterministic_archive  # noqa: E402
from opendesign_artifact import sha256_file, write_canonical_json  # noqa: E402
from opendesign_store_manifest import create_store_manifest  # noqa: E402
from opendesign_web_builder import (  # noqa: E402
    WebCacheKeys,
    _dependency_cache_paths,
    _restore_dependency_cache,
    _restore_session_dependency_cache,
    _restore_source_cache,
    _restore_workspace_build_cache,
    _write_dependency_cache,
    _write_session_dependency_cache,
    _write_source_cache,
    _write_workspace_build_cache,
    compute_web_cache_keys,
)
from opendesign_web_materialization import publish_web_overlay  # noqa: E402
from opendesign_web_rebind import WebRebindError, rebind_release_overlay  # noqa: E402
from opendesign_web_overlay import (  # noqa: E402
    WebOverlayError,
    verify_web_overlay,
    web_overlay_identity,
)
import opendesign_web_builder as web_builder  # noqa: E402


RUNTIME_DIGEST = "a" * 64
UPSTREAM_COMMIT = "b" * 40


class OpenDesignWebOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="maverick-od-web-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = self.root / "registry"
        self.registry.mkdir()
        self.key = self.root / "signing.pem"
        self.public_key = self.root / "trusted.pub.pem"
        self._create_key(self.key, self.public_key)
        self.trust = self.root / "trust.json"
        write_canonical_json(
            self.trust,
            {
                "schema_version": "1",
                "algorithm": "Ed25519",
                "public_key": self.public_key.name,
                "public_key_sha256": sha256_file(self.public_key),
            },
        )

    def test_verifies_signed_file_level_overlay_and_publishes_read_only(self) -> None:
        source, digest = self._overlay(self.key)

        overlay, cache_hit = publish_web_overlay(
            source,
            registry_root=self.registry,
            expected_digest=digest,
            trust_contract=self.trust,
        )

        self.assertFalse(cache_hit)
        self.assertEqual(overlay.web_overlay_sha256, digest)
        self.assertEqual(overlay.compatible_runtime_artifact_sha256, frozenset({RUNTIME_DIGEST}))
        self.assertEqual(overlay.static_dir.name, "static")
        self.assertEqual(overlay.path.stat().st_mode & 0o777, 0o555)
        self.assertEqual((overlay.static_dir / "index.html").stat().st_mode & 0o777, 0o444)
        again, cache_hit = publish_web_overlay(
            source,
            registry_root=self.registry,
            expected_digest=digest,
            trust_contract=self.trust,
        )
        self.assertTrue(cache_hit)
        self.assertEqual(again, overlay)

    def test_rejects_artifact_supplied_or_untrusted_signing_key(self) -> None:
        source, digest = self._overlay(self.key)
        attacker_key = self.root / "attacker.pem"
        attacker_public = self.root / "attacker.pub.pem"
        self._create_key(attacker_key, attacker_public)
        self._sign(source / "manifest.json", attacker_key, source / "manifest.sig")
        shutil.copy2(attacker_public, source / "public-key.pem")
        destination = self.registry / digest
        shutil.copytree(source, destination)

        with self.assertRaisesRegex(WebOverlayError, "signature|undeclared"):
            verify_web_overlay(
                destination,
                expected_digest=digest,
                registry_root=self.registry,
                trust_contract=self.trust,
            )

    def test_rejects_traversal_symlink_and_runtime_incompatibility(self) -> None:
        source, digest = self._overlay(self.key)
        outside = self.root / "outside.html"
        outside.write_text("outside", encoding="utf-8")
        (source / "static/index.html").unlink()
        (source / "static/index.html").symlink_to(outside)
        destination = self.registry / digest
        shutil.copytree(source, destination, symlinks=True)
        with self.assertRaisesRegex(WebOverlayError, "escape|real regular"):
            verify_web_overlay(
                destination,
                expected_digest=digest,
                registry_root=self.registry,
                trust_contract=self.trust,
            )

        shutil.rmtree(destination)
        source, digest = self._overlay(self.key, compatible_runtime="c" * 64)
        shutil.copytree(source, self.registry / digest)
        overlay = verify_web_overlay(
            self.registry / digest,
            expected_digest=digest,
            registry_root=self.registry,
            trust_contract=self.trust,
        )
        self.assertNotIn(RUNTIME_DIGEST, overlay.compatible_runtime_artifact_sha256)

    def test_v2_identity_binds_runtime_compatibility_and_modes(self) -> None:
        first, first_digest = self._overlay_v2(self.key, compatible_runtime=RUNTIME_DIGEST)
        second, second_digest = self._overlay_v2(self.key, compatible_runtime="c" * 64)

        self.assertNotEqual(first_digest, second_digest)
        first_overlay, first_hit = publish_web_overlay(
            first,
            registry_root=self.registry,
            expected_digest=first_digest,
            trust_contract=self.trust,
        )
        second_overlay, second_hit = publish_web_overlay(
            second,
            registry_root=self.registry,
            expected_digest=second_digest,
            trust_contract=self.trust,
        )

        self.assertFalse(first_hit)
        self.assertFalse(second_hit)
        self.assertEqual(first_overlay.compatible_runtime_artifact_sha256, frozenset({RUNTIME_DIGEST}))
        self.assertEqual(second_overlay.compatible_runtime_artifact_sha256, frozenset({"c" * 64}))
        (first_overlay.static_dir / "index.html").chmod(0o464)
        with self.assertRaisesRegex(WebOverlayError, "modes"):
            verify_web_overlay(
                first_overlay.path,
                expected_digest=first_digest,
                registry_root=self.registry,
                trust_contract=self.trust,
            )

    def test_rebinds_verified_v2_static_content_twice_for_one_exact_runtime(self) -> None:
        source, source_digest = self._overlay_v2(self.key, compatible_runtime=RUNTIME_DIGEST)
        published, _ = publish_web_overlay(
            source,
            registry_root=self.registry,
            expected_digest=source_digest,
            trust_contract=self.trust,
        )
        destination = self.root / "rebound-registry"
        work = self.root / "rebind-work"
        destination.mkdir()
        work.mkdir()
        service, manifest, target_runtime = self._rebind_inputs()

        result = rebind_release_overlay(
            source_registry_root=self.registry,
            source_web_overlay_sha256=source_digest,
            destination_registry_root=destination,
            bundle_manifest=manifest,
            service_root=service,
            signing_key=self.key,
            trust_contract=self.trust,
            work_parent=work,
        )

        self.assertEqual(result.derivations, 2)
        self.assertTrue(result.reproducible)
        self.assertFalse(result.cache_hit)
        self.assertNotEqual(result.overlay.web_overlay_sha256, source_digest)
        self.assertEqual(
            result.overlay.compatible_runtime_artifact_sha256,
            frozenset({target_runtime}),
        )
        self.assertEqual(
            sha256_file(result.overlay.path / "static.tar.gz"),
            sha256_file(published.path / "static.tar.gz"),
        )
        provenance = __import__("json").loads(
            (result.overlay.path / "provenance.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            provenance["compatibility_rebind"],
            {
                "method": "verified-static-content-v1",
                "source_web_overlay_sha256": source_digest,
                "target_runtime_artifact_sha256": target_runtime,
            },
        )

        cached = rebind_release_overlay(
            source_registry_root=self.registry,
            source_web_overlay_sha256=source_digest,
            destination_registry_root=destination,
            bundle_manifest=manifest,
            service_root=service,
            signing_key=self.key,
            trust_contract=self.trust,
            work_parent=work,
        )
        self.assertTrue(cached.cache_hit)
        self.assertEqual(cached.overlay, result.overlay)

    def test_rebind_rejects_tampered_or_legacy_source_overlay(self) -> None:
        source, source_digest = self._overlay_v2(self.key, compatible_runtime=RUNTIME_DIGEST)
        published, _ = publish_web_overlay(
            source,
            registry_root=self.registry,
            expected_digest=source_digest,
            trust_contract=self.trust,
        )
        destination = self.root / "rebound-reject-registry"
        work = self.root / "rebind-reject-work"
        destination.mkdir()
        work.mkdir()
        service, manifest, _target_runtime = self._rebind_inputs()
        (published.static_dir / "index.html").chmod(0o644)
        with self.assertRaisesRegex(WebOverlayError, "modes"):
            rebind_release_overlay(
                source_registry_root=self.registry,
                source_web_overlay_sha256=source_digest,
                destination_registry_root=destination,
                bundle_manifest=manifest,
                service_root=service,
                signing_key=self.key,
                trust_contract=self.trust,
                work_parent=work,
            )

        legacy_registry = self.root / "legacy-registry"
        legacy_registry.mkdir()
        legacy, legacy_digest = self._overlay(self.key, compatible_runtime=RUNTIME_DIGEST)
        publish_web_overlay(
            legacy,
            registry_root=legacy_registry,
            expected_digest=legacy_digest,
            trust_contract=self.trust,
        )
        with self.assertRaisesRegex(WebRebindError, "v2"):
            rebind_release_overlay(
                source_registry_root=legacy_registry,
                source_web_overlay_sha256=legacy_digest,
                destination_registry_root=destination,
                bundle_manifest=manifest,
                service_root=service,
                signing_key=self.key,
                trust_contract=self.trust,
                work_parent=work,
            )

    def test_v1_cache_collision_fails_closed(self) -> None:
        first, digest = self._overlay(self.key, compatible_runtime=RUNTIME_DIGEST)
        second, same_digest = self._overlay(self.key, compatible_runtime="c" * 64)
        self.assertEqual(digest, same_digest)
        publish_web_overlay(
            first,
            registry_root=self.registry,
            expected_digest=digest,
            trust_contract=self.trust,
        )

        with self.assertRaisesRegex(WebOverlayError, "identity collision"):
            publish_web_overlay(
                second,
                registry_root=self.registry,
                expected_digest=digest,
                trust_contract=self.trust,
            )

    def test_cache_keys_invalidate_only_the_affected_layers(self) -> None:
        source = self.root / "source"
        (source / "apps/web").mkdir(parents=True)
        (source / "pnpm-workspace.yaml").write_text("packages:\n  - apps/*\n", encoding="utf-8")
        (source / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        (source / "package.json").write_text('{"name":"root"}\n', encoding="utf-8")
        (source / "apps/web/package.json").write_text(
            '{"name":"web","dependencies":{"next":"15.5.7"}}\n',
            encoding="utf-8",
        )
        service = self.root / "service"
        (service / "patches").mkdir(parents=True)
        manifest = {
            "upstream": {"commit": UPSTREAM_COMMIT},
            "fallback_build": {"patch_series": "patches/series.json"},
        }

        def write_series(react_digest: str) -> None:
            write_canonical_json(
                service / "patches/series.json",
                {
                    "schema_version": "2",
                    "patches": [
                        {"component": "web-build", "sha256": "1" * 64},
                        {"component": "web-react", "sha256": react_digest},
                    ],
                },
            )

        write_series("2" * 64)
        baseline = compute_web_cache_keys(
            source,
            manifest=manifest,
            service_root=service,
            node_version="v24.11.0",
            pnpm_version="10.33.2",
        )
        write_series("3" * 64)
        react_changed = compute_web_cache_keys(
            source,
            manifest=manifest,
            service_root=service,
            node_version="v24.11.0",
            pnpm_version="10.33.2",
        )
        self.assertEqual(react_changed.dependency, baseline.dependency)
        self.assertEqual(react_changed.next, baseline.next)
        self.assertNotEqual(react_changed.source_build, baseline.source_build)

        parallel_build = compute_web_cache_keys(
            source,
            manifest=manifest,
            service_root=service,
            node_version="v24.11.0",
            pnpm_version="10.33.2",
            build_cpus=2,
        )
        self.assertEqual(parallel_build.dependency, react_changed.dependency)
        self.assertEqual(parallel_build.next, react_changed.next)
        self.assertNotEqual(parallel_build.source_build, react_changed.source_build)

        manifest["upstream"]["commit"] = "c" * 40
        upstream_changed = compute_web_cache_keys(
            source,
            manifest=manifest,
            service_root=service,
            node_version="v24.11.0",
            pnpm_version="10.33.2",
        )
        self.assertEqual(upstream_changed.dependency, parallel_build.dependency)
        self.assertNotEqual(upstream_changed.source_build, parallel_build.source_build)
        self.assertNotEqual(upstream_changed.next, parallel_build.next)

        (source / "pnpm-lock.yaml").write_text("lockfileVersion: '9.1'\n", encoding="utf-8")
        lock_changed = compute_web_cache_keys(
            source,
            manifest=manifest,
            service_root=service,
            node_version="v24.11.0",
            pnpm_version="10.33.2",
        )
        self.assertNotEqual(lock_changed.dependency, react_changed.dependency)
        self.assertNotEqual(lock_changed.source_build, react_changed.source_build)
        self.assertNotEqual(lock_changed.next, react_changed.next)

    def test_dependency_cache_inventory_excludes_already_contained_nested_roots(self) -> None:
        source = self.root / "dependency-source"
        for relative in (
            "node_modules/.pnpm/example/node_modules",
            "apps/web/node_modules",
            "apps/daemon/node_modules/.pnpm/nested/node_modules",
        ):
            (source / relative).mkdir(parents=True)

        paths = _dependency_cache_paths(source)

        self.assertEqual(paths, ["apps/daemon/node_modules", "apps/web/node_modules", "node_modules"])

    def test_private_session_dependency_cache_restores_by_hardlink_once(self) -> None:
        keys = WebCacheKeys("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64, "6" * 64)
        source = self.root / "session-source"
        package = source / "node_modules/demo/index.js"
        package.parent.mkdir(parents=True)
        package.write_text("verified dependency\n", encoding="utf-8")
        root = self.root / "session-cache"

        _write_session_dependency_cache(source, root, keys)
        shutil.rmtree(source / "node_modules")
        self.assertTrue(_restore_session_dependency_cache(source, root, keys))

        cached = root / keys.dependency / "payload/node_modules/demo/index.js"
        self.assertEqual(package.read_text(encoding="utf-8"), "verified dependency\n")
        self.assertEqual(package.stat().st_ino, cached.stat().st_ino)
        self.assertFalse(_restore_session_dependency_cache(source, root, keys))

    def test_cache_content_manifest_rejects_altered_source_and_dependency_payloads(self) -> None:
        keys = WebCacheKeys("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64, "6" * 64)
        cache = self.root / "cache"
        cache.mkdir()

        static = self.root / "static-cache-input"
        static.mkdir()
        (static / "index.html").write_text("verified\n", encoding="utf-8")
        source_root = cache / "source-build" / keys.source_build
        _write_source_cache(static, source_root, keys)
        (source_root / "static/index.html").write_text("altered\n", encoding="utf-8")
        self.assertFalse(_restore_source_cache(source_root, self.root / "static-restore", keys))

        dependencies = self.root / "dependency-input"
        (dependencies / "node_modules/example").mkdir(parents=True)
        (dependencies / "node_modules/example/index.js").write_text("verified\n", encoding="utf-8")
        dependency_root = cache / "dependencies" / keys.dependency
        _write_dependency_cache(dependencies, dependency_root, keys)
        archive = dependency_root / "payload.tar"
        archive.write_bytes(archive.read_bytes() + b"altered\n")
        restore_source = self.root / "dependency-restore"
        restore_source.mkdir()
        self.assertFalse(_restore_dependency_cache(restore_source, dependency_root, keys))
        self.assertFalse((restore_source / "node_modules").exists())

    def test_same_key_cache_publication_is_locked_and_immutable(self) -> None:
        keys = WebCacheKeys("a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64, "f" * 64)
        cache = self.root / "concurrent-cache"
        cache.mkdir()
        first = self.root / "first-static"
        second = self.root / "second-static"
        first.mkdir()
        second.mkdir()
        (first / "index.html").write_text("first\n", encoding="utf-8")
        (second / "index.html").write_text("second\n", encoding="utf-8")
        root = cache / "source-build" / keys.source_build

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda source: _write_source_cache(source, root, keys), (first, second)))

        self.assertEqual(results, [None, None])
        destination = self.root / "concurrent-restore"
        self.assertTrue(_restore_source_cache(root, destination, keys))
        self.assertIn((destination / "index.html").read_text(encoding="utf-8"), {"first\n", "second\n"})
        marker = __import__("json").loads((root / "complete.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["schema_version"], "3")
        self.assertEqual(len(marker["content_manifest_sha256"]), 64)

    def test_workspace_build_cache_restores_verified_outputs_only(self) -> None:
        keys = WebCacheKeys("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64, "6" * 64)
        source = self.root / "workspace-source"
        output = source / "packages/components/dist"
        output.mkdir(parents=True)
        (output / "index.js").write_text("verified\n", encoding="utf-8")
        root = self.root / "cache/workspace-build" / keys.next

        _write_workspace_build_cache(source, root, keys)
        (output / "index.js").write_text("stale install output\n", encoding="utf-8")
        self.assertTrue(_restore_workspace_build_cache(source, root, keys))
        self.assertEqual((output / "index.js").read_text(encoding="utf-8"), "verified\n")

        (root / "payload/packages/components/dist/index.js").write_text("altered\n", encoding="utf-8")
        shutil.rmtree(output)
        self.assertFalse(_restore_workspace_build_cache(source, root, keys))
        self.assertFalse(output.exists())

    def test_release_derivations_do_not_share_dependency_or_compiled_caches(self) -> None:
        keys = WebCacheKeys("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64, "6" * 64)
        metric = web_builder.WebBuildMetrics(1.0, False, False, False, False)
        observed: list[dict] = []

        def derive(_repository, result_root, **kwargs):
            observed.append(kwargs)
            result_root.mkdir(parents=True)
            (result_root / "static.tar.gz").write_bytes(b"release")
            write_canonical_json(result_root / "manifest.json", {"web_overlay_sha256": "7" * 64})
            return result_root, keys, metric

        overlay = Mock(web_overlay_sha256="7" * 64)
        work = self.root / "release-work"
        work.mkdir()
        with patch.object(web_builder, "_derive_once", side_effect=derive):
            with patch.object(web_builder, "_assert_byte_reproducible"):
                with patch.object(web_builder, "sha256_file", return_value="7" * 64):
                    with patch.object(web_builder, "publish_web_overlay", return_value=(overlay, False)):
                        result = web_builder.build_release_overlay(
                            self.root,
                            manifest={},
                            service_root=self.root,
                            cache_root=self.root / "cache",
                            registry_root=self.registry,
                            signing_key=self.key,
                            trust_contract=self.trust,
                            work_parent=work,
                        )

        self.assertEqual(result.derivations, 2)
        self.assertTrue(result.reproducible)
        self.assertEqual(len(observed), 2)
        self.assertTrue(all(call["allow_dependency_cache"] is False for call in observed))
        self.assertTrue(all(call["allow_source_cache"] is False for call in observed))
        self.assertTrue(all(call["allow_next_cache"] is False for call in observed))

    def _overlay(self, signing_key: Path, *, compatible_runtime: str = RUNTIME_DIGEST) -> tuple[Path, str]:
        root = self.root / f"source-{len(list(self.root.glob('source-*')))}"
        static = root / "static"
        static.mkdir(parents=True)
        (static / "index.html").write_text("<html>overlay</html>\n", encoding="utf-8")
        files = {
            "schema_version": "1",
            "files": [
                {
                    "path": "index.html",
                    "sha256": sha256_file(static / "index.html"),
                    "size_bytes": (static / "index.html").stat().st_size,
                }
            ],
        }
        write_canonical_json(root / "files.json", files)
        write_deterministic_archive(static, root / "static.tar.gz")
        digest = sha256_file(root / "static.tar.gz")
        write_canonical_json(root / "sbom.cdx.json", {"bomFormat": "CycloneDX"})
        write_canonical_json(root / "licenses.json", {"schema_version": "1", "packages": []})
        (root / "NOTICE").write_text("Test notice\n", encoding="utf-8")
        write_canonical_json(
            root / "provenance.json",
            {"schema_version": "1", "subject": {"web_overlay_sha256": digest}},
        )

        def descriptor(name: str) -> dict[str, object]:
            path = root / name
            return {"path": name, "sha256": sha256_file(path), "size_bytes": path.stat().st_size}

        write_canonical_json(
            root / "manifest.json",
            {
                "schema_version": "1",
                "web_overlay_sha256": digest,
                "static_archive": descriptor("static.tar.gz"),
                "file_manifest": descriptor("files.json"),
                "compatibility": {
                    "runtime_artifact_sha256": [compatible_runtime],
                    "od_version": "0.16.1",
                    "upstream_commit": UPSTREAM_COMMIT,
                    "platform": {"os": "linux", "architecture": "amd64"},
                },
                "inputs": {
                    "lockfile_sha256": "1" * 64,
                    "package_graph_sha256": "2" * 64,
                    "web_build_patch_sha256": "3" * 64,
                    "web_react_patch_sha256": "4" * 64,
                    "node": "v24.11.0",
                    "pnpm": "10.33.2",
                    "toolchain_sha256": "5" * 64,
                },
                "sbom": descriptor("sbom.cdx.json"),
                "licenses": descriptor("licenses.json"),
                "notice": descriptor("NOTICE"),
                "provenance": descriptor("provenance.json"),
                "signature": {"algorithm": "Ed25519", "path": "manifest.sig"},
            },
        )
        self._sign(root / "manifest.json", signing_key, root / "manifest.sig")
        return root, digest

    def _rebind_inputs(self) -> tuple[Path, dict, str]:
        target_runtime = "c" * 64
        service = self.root / "rebind-service"
        (service / "patches").mkdir(parents=True, exist_ok=True)
        write_canonical_json(
            service / "patches/series.json",
            {
                "schema_version": "2",
                "patches": [
                    {"component": "web-build", "sha256": "3" * 64},
                    {"component": "web-react", "sha256": "4" * 64},
                ],
            },
        )
        manifest = {
            "upstream": {"release_version": "0.16.1", "commit": UPSTREAM_COMMIT},
            "distribution": {"platform": {"os": "linux", "architecture": "amd64"}},
            "fallback_build": {"patch_series": "patches/series.json"},
            "artifact": {
                "format": "tar.gz",
                "default_relative_path": "external-capability/opendesign/runtime",
                "asset_directory": "artifacts",
                "assets": {
                    "linux-x86_64": {
                        "file": "runtime.tar.gz",
                        "sha256": target_runtime,
                        "size_bytes": 1,
                        "file_manifest": "runtime.manifest.json",
                        "file_manifest_sha256": "d" * 64,
                        "sbom": "runtime.sbom.json",
                        "sbom_sha256": "e" * 64,
                        "license_inventory": "runtime.licenses.json",
                        "license_inventory_sha256": "f" * 64,
                        "notice": "runtime.NOTICE",
                        "notice_sha256": "1" * 64,
                        "provenance": "runtime.provenance.json",
                        "provenance_sha256": "2" * 64,
                        "signature": "runtime.sig",
                        "signature_sha256": "3" * 64,
                        "public_key": "runtime.pub.pem",
                        "public_key_sha256": "4" * 64,
                    }
                }
            },
        }
        return service, manifest, target_runtime

    def _overlay_v2(self, signing_key: Path, *, compatible_runtime: str) -> tuple[Path, str]:
        root = self.root / f"source-v2-{len(list(self.root.glob('source-v2-*')))}"
        static = root / "static"
        static.mkdir(parents=True)
        (static / "index.html").write_text("<html>overlay</html>\n", encoding="utf-8")
        (static / "index.html").chmod(0o444)
        write_canonical_json(root / "files.json", create_store_manifest(static))
        write_deterministic_archive(static, root / "static.tar.gz")
        write_canonical_json(root / "sbom.cdx.json", {"bomFormat": "CycloneDX"})
        write_canonical_json(root / "licenses.json", {"schema_version": "1", "packages": []})
        (root / "NOTICE").write_text("Test notice\n", encoding="utf-8")
        compatibility = {
            "runtime_artifact_sha256": [compatible_runtime],
            "od_version": "0.16.1",
            "upstream_commit": UPSTREAM_COMMIT,
            "platform": {"os": "linux", "architecture": "amd64"},
        }
        inputs = {
            "lockfile_sha256": "1" * 64,
            "package_graph_sha256": "2" * 64,
            "web_build_patch_sha256": "3" * 64,
            "web_react_patch_sha256": "4" * 64,
            "node": "v24.11.0",
            "pnpm": "10.33.2",
            "toolchain_sha256": "5" * 64,
        }

        def descriptor(name: str) -> dict[str, object]:
            path = root / name
            return {"path": name, "sha256": sha256_file(path), "size_bytes": path.stat().st_size}

        digest = web_overlay_identity(
            static_archive_sha256=sha256_file(root / "static.tar.gz"),
            file_manifest_sha256=sha256_file(root / "files.json"),
            sbom_sha256=sha256_file(root / "sbom.cdx.json"),
            licenses_sha256=sha256_file(root / "licenses.json"),
            notice_sha256=sha256_file(root / "NOTICE"),
            compatibility=compatibility,
            inputs=inputs,
        )
        write_canonical_json(
            root / "provenance.json",
            {"schema_version": "2", "subject": {"web_overlay_sha256": digest}},
        )
        write_canonical_json(
            root / "manifest.json",
            {
                "schema_version": "2",
                "web_overlay_sha256": digest,
                "static_archive": descriptor("static.tar.gz"),
                "file_manifest": descriptor("files.json"),
                "compatibility": compatibility,
                "inputs": inputs,
                "sbom": descriptor("sbom.cdx.json"),
                "licenses": descriptor("licenses.json"),
                "notice": descriptor("NOTICE"),
                "provenance": descriptor("provenance.json"),
                "signature": {"algorithm": "Ed25519", "path": "manifest.sig"},
            },
        )
        self._sign(root / "manifest.json", signing_key, root / "manifest.sig")
        return root, digest

    @staticmethod
    def _create_key(private_key: Path, public_key: Path) -> None:
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(private_key)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @staticmethod
    def _sign(manifest: Path, key: Path, signature: Path) -> None:
        subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-rawin",
                "-inkey",
                str(key),
                "-in",
                str(manifest),
                "-out",
                str(signature),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    unittest.main()
