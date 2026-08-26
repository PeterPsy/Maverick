from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
MANIFEST_PATH = SERVICE_ROOT / "opendesign_bundle.json"
UPSTREAM_COMMIT = "276b4d8e970bc143d7ad060181a89a834e3d9caf"
WEB_DIGEST = "e" * 64


def _load_module(name: str, path: Path):
    sys.path.insert(0, str(SERVICE_ROOT))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class OpenDesignMaterializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = _load_module("opendesign_artifact", SERVICE_ROOT / "opendesign_artifact.py")
        cls.archive = _load_module("opendesign_archive", SERVICE_ROOT / "opendesign_archive.py")
        _load_module(
            "opendesign_generation_model",
            SERVICE_ROOT / "opendesign_generation_model.py",
        )
        _load_module(
            "opendesign_generation_control",
            SERVICE_ROOT / "opendesign_generation_control.py",
        )
        cls.materialization = _load_module(
            "opendesign_materialization",
            SERVICE_ROOT / "opendesign_materialization.py",
        )
        cls.runtime = _load_module("opendesign_runtime", SERVICE_ROOT / "opendesign_runtime.py")
        cls.launcher = _load_module("opendesign_launcher", SERVICE_ROOT / "opendesign_launcher.py")
        cls.bootstrap = _load_module("opendesign_bootstrap", SERVICE_ROOT / "opendesign_bootstrap.py")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="maverick-od-materialize-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive_path, self.archive_sha256, self.file_manifest_sha256 = self._fixture_archive()

    def test_materialization_is_atomic_immutable_and_idempotent(self) -> None:
        registry = self.root / "registry"
        first = self._materialize(registry)
        second = self._materialize(registry)

        self.assertEqual(first, second)
        self.assertEqual(first.path, registry / self.archive_sha256)
        self.assertFalse(first.path.is_symlink())
        self.assertEqual(
            self.materialization.discover_verified_bundles(registry)[self.archive_sha256],
            first,
        )
        self.assertFalse(any(path.name.startswith(".materialize-") for path in registry.iterdir()))

    def test_launcher_accepts_only_the_declared_artifact_capability_mount(self) -> None:
        external = self.root / "operational-registry"
        external.mkdir()
        with patch.dict(
            "os.environ",
            {
                "MAVERICK_OPENDESIGN_STORE_ROOT": str(external),
                "MAVERICK_OPENDESIGN_ALLOW_EXTERNAL_BUNDLE": "1",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(self.launcher.LauncherError, "declared artifact capability mount"):
                self.launcher._store_root()

    def test_missing_runtime_closure_is_classified_as_repairable_integrity_failure(self) -> None:
        bundle_root = self.root / "protected-runtime"
        daemon_root = bundle_root / "app/apps/daemon"
        daemon_root.mkdir(parents=True)
        binding = SimpleNamespace(bundle=SimpleNamespace(path=bundle_root))

        with self.assertRaises(self.launcher.ArtifactStoreError) as missing_manifest:
            self.launcher._resolve_launch_plan(binding, self._pinned_manifest())
        self.assertEqual(missing_manifest.exception.code, "artifact_integrity_mismatch")
        self.assertEqual(missing_manifest.exception.phase, "runtime_closure_verify")
        self.assertEqual(missing_manifest.exception.differences, 1)

        (daemon_root / "package.json").write_text("{}\n", encoding="utf-8")
        with self.assertRaises(self.launcher.ArtifactStoreError) as missing_dependencies:
            self.launcher._resolve_launch_plan(binding, self._pinned_manifest())
        self.assertEqual(missing_dependencies.exception.code, "artifact_integrity_mismatch")
        self.assertEqual(missing_dependencies.exception.phase, "runtime_closure_verify")
        self.assertEqual(missing_dependencies.exception.differences, 1)

        (daemon_root / "node_modules").mkdir()
        with self.assertRaises(self.launcher.ArtifactStoreError) as missing_runtime:
            self.launcher._resolve_launch_plan(binding, self._pinned_manifest())
        self.assertEqual(missing_runtime.exception.code, "artifact_integrity_mismatch")
        self.assertEqual(missing_runtime.exception.phase, "runtime_closure_verify")

    def test_launcher_finalizes_recovery_only_after_verified_readiness(self) -> None:
        plan = self.launcher.LaunchPlan("test", ["daemon"], self.root, "test")
        binding = SimpleNamespace()
        daemon = Mock()
        daemon.wait.return_value = 0
        readiness = {"ready": True, "service_count": 1}

        with (
            patch.object(self.launcher.subprocess, "Popen", return_value=daemon),
            patch.object(
                self.launcher,
                "_wait_for_sidecar_readiness",
                return_value=readiness,
            ) as wait_for_readiness,
            patch.object(self.launcher, "_finalize_pending_activations") as finalize,
            patch.object(self.launcher, "_write_readiness_marker") as write_marker,
            patch.object(self.launcher, "_wait_for_maverick_readiness") as wait_for_maverick,
            self.assertRaises(self.launcher.LauncherError) as exited,
        ):
            self.launcher._run_daemon(
                plan,
                {"OD_PORT": "1234", "OD_API_TOKEN": "token"},
                generation_root=self.root / "generation",
                binding=binding,
                web_registry_root=self.root / "web-registry",
                startup_id="startup-test",
                timings={},
            )

        self.assertEqual(exited.exception.code, "daemon_spawn_failed")
        self.assertEqual(exited.exception.phase, "daemon_exit")
        wait_for_readiness.assert_called_once_with(
            daemon,
            env={"OD_PORT": "1234", "OD_API_TOKEN": "token"},
        )
        finalize.assert_called_once_with(
            self.root / "generation",
            binding=binding,
            web_registry_root=self.root / "web-registry",
            readiness=readiness,
        )
        write_marker.assert_called_once_with(
            self.root / "generation",
            binding=binding,
            startup_nonce="startup-test",
        )
        wait_for_maverick.assert_called_once_with(
            daemon,
            env={"OD_PORT": "1234", "OD_API_TOKEN": "token"},
        )

    def test_launcher_heartbeat_fails_closed_when_transactional_readiness_is_lost(self) -> None:
        daemon = Mock()
        daemon.wait.side_effect = subprocess.TimeoutExpired(cmd="daemon", timeout=1)
        with (
            patch.object(
                self.launcher,
                "_wait_for_json_readiness",
                return_value={"ready": False},
            ) as readiness,
            patch.object(self.launcher, "_update_health_status"),
            self.assertRaises(self.launcher.LauncherError) as raised,
        ):
            self.launcher._wait_for_daemon_exit(
                daemon,
                env={"OD_PORT": "1234", "OD_API_TOKEN": "token"},
                generation_root=self.root / "generation",
                startup_id="startup-test",
                timings={},
            )

        self.assertEqual(raised.exception.code, "activation_incomplete")
        self.assertEqual(raised.exception.phase, "readiness_monitor")
        readiness.assert_called_once_with(
            daemon,
            env={"OD_PORT": "1234", "OD_API_TOKEN": "token"},
            path="/api/maverick-ready",
            timeout_seconds=0.75,
        )

    def test_existing_digest_directory_is_never_replaced_after_tampering(self) -> None:
        registry = self.root / "registry"
        installed = self._materialize(registry)
        cli = installed.path / "app/apps/daemon/dist/cli.js"
        cli.write_text("tampered\n", encoding="utf-8")

        with self.assertRaisesRegex(self.artifact.ArtifactError, "invalid and was not replaced"):
            self._materialize(registry)

        self.assertEqual(cli.read_text(encoding="utf-8"), "tampered\n")
        self.assertEqual([path.name for path in registry.iterdir()], [self.archive_sha256])

    def test_targeted_discovery_fully_verifies_only_requested_executable_bundles(self) -> None:
        registry = self.root / "registry"
        installed = self._materialize(registry)
        retained_digest = "d" * 64
        retained = registry / retained_digest
        shutil.copytree(installed.path, retained)
        marker_path = retained / self.archive.MATERIALIZED_MARKER_PATH
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["artifact_sha256"] = retained_digest
        self.artifact.write_canonical_json(marker_path, marker)
        (retained / "app/apps/web/out/index.html").write_text("tampered", encoding="utf-8")

        requested = self.materialization.discover_verified_bundles(
            registry,
            required_digests={self.archive_sha256},
        )

        self.assertEqual(set(requested), {self.archive_sha256})
        with self.assertRaisesRegex(self.artifact.ArtifactError, "manifest mismatch"):
            self.materialization.discover_verified_bundles(registry)

    def test_traversal_archive_is_rejected_and_owned_stage_is_removed(self) -> None:
        malicious = self.root / "malicious.tar.gz"
        with tarfile.open(malicious, mode="w:gz") as bundle:
            member = tarfile.TarInfo("../escape")
            member.size = 0
            bundle.addfile(member)
        digest = self.artifact.sha256_file(malicious)
        registry = self.root / "registry"

        with self.assertRaisesRegex(self.artifact.ArtifactError, "Unsafe"):
            self.materialization.materialize_archive(
                malicious,
                registry,
                expected_artifact_sha256=digest,
                expected_file_manifest_sha256="a" * 64,
                opendesign_version="0.16.1",
                upstream_commit=UPSTREAM_COMMIT,
            )

        self.assertFalse((self.root / "escape").exists())
        self.assertEqual(list(registry.iterdir()), [])

    def test_archive_symlink_ancestor_pivot_is_rejected_before_fast_extraction(self) -> None:
        malicious = self.root / "symlink-pivot.tar.gz"
        with tarfile.open(malicious, mode="w:gz") as bundle:
            pivot = tarfile.TarInfo("pivot")
            pivot.type = tarfile.SYMTYPE
            pivot.linkname = "target"
            bundle.addfile(pivot)
            nested = tarfile.TarInfo("pivot/escaped.txt")
            nested.size = len(b"escaped")
            import io

            bundle.addfile(nested, io.BytesIO(b"escaped"))
        digest = self.artifact.sha256_file(malicious)
        registry = self.root / "registry-symlink-pivot"

        with self.assertRaisesRegex(self.artifact.ArtifactError, "traverses a symlink"):
            self.materialization.materialize_archive(
                malicious,
                registry,
                expected_artifact_sha256=digest,
                expected_file_manifest_sha256="a" * 64,
                opendesign_version="0.16.1",
                upstream_commit=UPSTREAM_COMMIT,
            )

        self.assertFalse((registry / "target/escaped.txt").exists())
        self.assertFalse(any(registry.iterdir()))

    def test_runtime_binding_uses_only_the_controlled_bundle_data_pair(self) -> None:
        registry = self.root / "registry"
        installed = self._materialize(registry)
        generation_root = self.root / "data-root"
        generation_root.mkdir()
        for name in ("instances", "migrations", "backups", "web-activations"):
            (generation_root / name).mkdir()
        overlay_root = self.root / "web-registry" / WEB_DIGEST
        (overlay_root / "static").mkdir(parents=True)
        overlay = SimpleNamespace(
            web_overlay_sha256=WEB_DIGEST,
            path=overlay_root,
            static_dir=overlay_root / "static",
            od_version="0.16.1",
            upstream_commit=UPSTREAM_COMMIT,
            compatible_runtime_artifact_sha256=frozenset({self.archive_sha256}),
        )
        control, data_dir = self.bootstrap.bootstrap_empty_generation(
            generation_root,
            artifact_sha256=self.archive_sha256,
            web_overlay_sha256=WEB_DIGEST,
            opendesign_version="0.16.1",
            verified_artifacts={self.archive_sha256: "0.16.1"},
            verified_overlays={WEB_DIGEST: overlay},
            now=lambda: "2026-08-04T00:00:00Z",
        )

        with (
            patch.object(
                self.runtime,
                "discover_verified_bundles",
                wraps=self.materialization.discover_verified_bundles,
            ) as discovery,
            patch.object(
                self.runtime,
                "discover_verified_overlays",
                return_value={WEB_DIGEST: overlay},
            ),
        ):
            binding = self.runtime.resolve_runtime_binding(
                registry_root=registry,
                web_registry_root=self.root / "web-registry",
                web_trust_contract=SERVICE_ROOT / "opendesign_web_trust.json",
                generation_root=generation_root,
                manifest=self._pinned_manifest(),
            )
        plan = self.launcher._resolve_launch_plan(binding, self._pinned_manifest())
        daemon_env = self.launcher._daemon_env(
            data_dir=binding.data_dir,
            media_config_dir=binding.data_dir / "media-config",
            static_dir=binding.overlay.static_dir,
            static_registry_root=binding.overlay.path,
            generation_root=generation_root,
            binding=binding,
            startup_nonce="startup-test",
        )

        self.assertEqual(binding.bundle, installed)
        self.assertEqual(binding.data_dir, data_dir)
        self.assertEqual(binding.active, control.active)
        self.assertEqual(plan.mode, "oci-musl-runtime")
        self.assertEqual(plan.cwd, installed.path / "app")
        self.assertEqual(plan.command[0], str(installed.path / "runtime/lib/ld-musl-x86_64.so.1"))
        self.assertEqual(plan.command[3], str(installed.path / "runtime/bin/node"))
        self.assertEqual(daemon_env["OD_DATA_DIR"], str(data_dir))
        self.assertEqual(daemon_env["OD_STATIC_DIR"], str(binding.overlay.static_dir))
        self.assertEqual(daemon_env["OD_STATIC_REGISTRY_ROOT"], str(binding.overlay.path))
        self.assertEqual(daemon_env["OD_MAVERICK_STARTUP_NONCE"], "startup-test")
        self.assertEqual(daemon_env["OD_RUNTIME_ARTIFACT_SHA256"], self.archive_sha256)
        self.assertEqual(daemon_env["OD_WEB_OVERLAY_SHA256"], WEB_DIGEST)
        self.assertEqual(
            daemon_env["MAVERICK_OPENDESIGN_NODE_COMPILE_CACHE"],
            str(data_dir / "cache" / "node-compile" / self.archive_sha256),
        )
        self.assertEqual(daemon_env["OD_REQUIRE_API_TOKEN_ON_LOOPBACK"], "1")
        self.assertEqual(daemon_env["DO_NOT_TRACK"], "1")
        self.assertEqual(daemon_env["NEXT_TELEMETRY_DISABLED"], "1")
        self.assertEqual(
            discovery.call_args.kwargs["required_digests"],
            {self.archive_sha256},
        )

    def test_runtime_binding_rejects_uncontrolled_or_tampered_state(self) -> None:
        registry = self.root / "registry"
        installed = self._materialize(registry)
        generation_root = self.root / "data-root"
        (generation_root / "instances/gen_current/data").mkdir(parents=True)
        (generation_root / "migrations").mkdir()
        (generation_root / "backups").mkdir()
        (generation_root / "web-activations").mkdir()
        (generation_root / "control.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "active": {
                        "bundle_artifact_sha256": "f" * 64,
                        "od_version": "0.16.1",
                        "data_generation": "gen_current",
                    },
                    "previous": None,
                    "migration_id": None,
                    "updated_at": "2026-08-04T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(self.artifact.ArtifactError, "invalid|not materialized|not verified"):
            self.runtime.resolve_runtime_binding(
                registry_root=registry,
                web_registry_root=self.root / "web-registry",
                web_trust_contract=SERVICE_ROOT / "opendesign_web_trust.json",
                generation_root=generation_root,
                manifest=self._pinned_manifest(),
            )

        (installed.path / "app/apps/web/out/index.html").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(self.artifact.ArtifactError, "manifest mismatch"):
            self.materialization.discover_verified_bundles(registry)

    def test_launcher_requires_a_nonblank_token_and_forces_private_runtime_env(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(SystemExit, "OD_API_TOKEN is required"):
                self.launcher._required_env("OD_API_TOKEN")
        with patch.dict("os.environ", {"OD_API_TOKEN": "   "}, clear=True):
            with self.assertRaisesRegex(SystemExit, "OD_API_TOKEN is required"):
                self.launcher._required_env("OD_API_TOKEN")
        with patch.dict(
            "os.environ",
            {
                "OD_API_TOKEN": "technical-token",
                "DO_NOT_TRACK": "0",
                "NEXT_TELEMETRY_DISABLED": "0",
            },
            clear=True,
        ):
            binding = SimpleNamespace(
                active=SimpleNamespace(
                    runtime_artifact_sha256="a" * 64,
                    web_overlay_sha256="b" * 64,
                    data_generation="gen_current",
                ),
                control=SimpleNamespace(runtime_activation_id=None, web_activation_id=None),
            )
            environment = self.launcher._daemon_env(
                data_dir=self.root / "data",
                media_config_dir=self.root / "data/media-config",
                static_dir=self.root / "static",
                static_registry_root=self.root,
                generation_root=self.root / "generation",
                binding=binding,
                startup_nonce="startup-test",
            )
        self.assertEqual(environment["OD_API_TOKEN"], "technical-token")
        self.assertEqual(environment["OD_REQUIRE_API_TOKEN_ON_LOOPBACK"], "1")
        self.assertEqual(environment["DO_NOT_TRACK"], "1")
        self.assertEqual(environment["NEXT_TELEMETRY_DISABLED"], "1")

    def test_launcher_rejects_runtime_subdirectory_symlinks(self) -> None:
        data_dir = self.root / "active-data"
        outside = self.root / "outside"
        data_dir.mkdir()
        outside.mkdir()
        (data_dir / "db").symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(SystemExit, "must be a real directory"):
            self.launcher._ensure_runtime_dirs(data_dir, data_dir / "media-config")

    def test_launcher_rejects_compile_cache_symlinks_and_invalid_runtime_digest(self) -> None:
        data_dir = self.root / "active-cache-data"
        outside = self.root / "outside-cache"
        (data_dir / "cache").mkdir(parents=True)
        outside.mkdir()
        (data_dir / "cache/node-compile").symlink_to(outside, target_is_directory=True)
        cache_dir = data_dir / "cache/node-compile" / self.archive_sha256

        with self.assertRaisesRegex(SystemExit, "must be a real directory"):
            self.launcher._ensure_runtime_dirs(
                data_dir,
                data_dir / "media-config",
                node_compile_cache_dir=cache_dir,
            )
        with self.assertRaisesRegex(self.launcher.LauncherError, "digest is invalid"):
            self.launcher._node_compile_cache_dir(data_dir, "not-a-digest")

    def test_empty_bootstrap_refuses_legacy_or_unknown_data(self) -> None:
        generation_root = self.root / "data-root"
        generation_root.mkdir()
        for name in ("instances", "migrations", "backups", "web-activations"):
            (generation_root / name).mkdir()
        (generation_root / "app.sqlite").write_bytes(b"legacy")

        with self.assertRaisesRegex(self.bootstrap.BootstrapError, "controlled migration"):
            self.bootstrap.bootstrap_empty_generation(
                generation_root,
                artifact_sha256=self.archive_sha256,
                web_overlay_sha256=WEB_DIGEST,
                opendesign_version="0.16.1",
                verified_artifacts={self.archive_sha256: "0.16.1"},
                verified_overlays={
                    WEB_DIGEST: {
                        "od_version": "0.16.1",
                        "compatible_runtime_artifact_sha256": [self.archive_sha256],
                    }
                },
            )

        self.assertEqual(list((generation_root / "instances").iterdir()), [])

    def _materialize(self, registry: Path):
        return self.materialization.materialize_archive(
            self.archive_path,
            registry,
            expected_artifact_sha256=self.archive_sha256,
            expected_file_manifest_sha256=self.file_manifest_sha256,
            opendesign_version="0.16.1",
            upstream_commit=UPSTREAM_COMMIT,
        )

    def _fixture_archive(self) -> tuple[Path, str, str]:
        stage = self.root / "stage"
        files = {
            "app/apps/daemon/package.json": '{"name":"@open-design/daemon","version":"0.16.1"}\n',
            "app/apps/daemon/dist/cli.js": "process.exit(0);\n",
            "app/apps/daemon/node_modules/.modules.yaml": "layoutVersion: 5\n",
            "app/apps/web/out/index.html": "<!doctype html><title>OpenDesign</title>\n",
            "runtime/bin/node": "fixture-node\n",
            "runtime/lib/ld-musl-x86_64.so.1": "fixture-loader\n",
            "runtime/lib/libc.musl-x86_64.so.1": "fixture-libc\n",
            "runtime/usr-lib/libstdc++.so.6": "fixture-libstdc++\n",
            "maverick/oci.json": '{"schema_version":"1"}\n',
        }
        for relative, content in files.items():
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        file_manifest = self.archive.create_file_manifest(
            stage,
            exclude={self.archive.FILE_MANIFEST_PATH},
        )
        manifest_path = stage / self.archive.FILE_MANIFEST_PATH
        self.artifact.write_canonical_json(manifest_path, file_manifest)
        output = self.root / "fixture.tar.gz"
        self.archive.write_deterministic_archive(stage, output)
        return output, self.artifact.sha256_file(output), self.artifact.sha256_file(manifest_path)

    def _pinned_manifest(self) -> dict:
        manifest = copy.deepcopy(self.artifact.read_bundle_manifest(MANIFEST_PATH))
        asset = manifest["artifact"]["assets"][self.artifact.platform_key()]
        asset["sha256"] = self.archive_sha256
        asset["file_manifest_sha256"] = self.file_manifest_sha256
        asset["size_bytes"] = self.archive_path.stat().st_size
        for _path_field, digest_field in self.artifact.ARTIFACT_DIGEST_FIELDS.items():
            if asset[digest_field] is None:
                asset[digest_field] = "c" * 64
        return manifest


if __name__ == "__main__":
    unittest.main()
