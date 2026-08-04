from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
MANIFEST_PATH = SERVICE_ROOT / "opendesign_bundle.json"
UPSTREAM_COMMIT = "276b4d8e970bc143d7ad060181a89a834e3d9caf"


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
        _load_module("opendesign_generation_control", SERVICE_ROOT / "opendesign_generation_control.py")
        cls.materialization = _load_module(
            "opendesign_materialization",
            SERVICE_ROOT / "opendesign_materialization.py",
        )
        cls.runtime = _load_module("opendesign_runtime", SERVICE_ROOT / "opendesign_runtime.py")
        cls.launcher = _load_module("opendesign_launcher", SERVICE_ROOT / "opendesign_launcher.py")
        cls.generation = sys.modules["opendesign_generation_control"]

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

    def test_existing_digest_directory_is_never_replaced_after_tampering(self) -> None:
        registry = self.root / "registry"
        installed = self._materialize(registry)
        cli = installed.path / "apps/daemon/dist/cli.js"
        cli.write_text("tampered\n", encoding="utf-8")

        with self.assertRaisesRegex(self.artifact.ArtifactError, "invalid and was not replaced"):
            self._materialize(registry)

        self.assertEqual(cli.read_text(encoding="utf-8"), "tampered\n")
        self.assertEqual([path.name for path in registry.iterdir()], [self.archive_sha256])

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

    def test_runtime_binding_uses_only_the_controlled_bundle_data_pair(self) -> None:
        registry = self.root / "registry"
        installed = self._materialize(registry)
        generation_root = self.root / "data-root"
        data_dir = generation_root / "instances/gen_current/data"
        data_dir.mkdir(parents=True)
        (generation_root / "migrations").mkdir()
        (generation_root / "backups").mkdir()
        triple = self.generation.GenerationTriple(
            self.archive_sha256,
            "0.16.1",
            "gen_current",
        )
        control = self.generation.GenerationControl(
            active=triple,
            previous=None,
            migration_id=None,
            updated_at="2026-08-04T00:00:00Z",
        )
        self.generation.write_generation_control(
            generation_root,
            control,
            verified_artifacts={self.archive_sha256: "0.16.1"},
        )

        binding = self.runtime.resolve_runtime_binding(
            registry_root=registry,
            generation_root=generation_root,
            manifest=self._pinned_manifest(),
        )
        plan = self.launcher._resolve_launch_plan(binding)
        daemon_env = self.launcher._daemon_env(
            data_dir=binding.data_dir,
            media_config_dir=binding.data_dir / "media-config",
        )

        self.assertEqual(binding.bundle, installed)
        self.assertEqual(binding.data_dir, data_dir)
        self.assertEqual(plan.mode, "curated-dist")
        self.assertEqual(plan.cwd, installed.path)
        self.assertEqual(daemon_env["OD_DATA_DIR"], str(data_dir))
        self.assertEqual(daemon_env["OD_REQUIRE_API_TOKEN_ON_LOOPBACK"], "1")
        self.assertEqual(daemon_env["DO_NOT_TRACK"], "1")
        self.assertEqual(daemon_env["NEXT_TELEMETRY_DISABLED"], "1")

    def test_runtime_binding_rejects_uncontrolled_or_tampered_state(self) -> None:
        registry = self.root / "registry"
        installed = self._materialize(registry)
        generation_root = self.root / "data-root"
        (generation_root / "instances/gen_current/data").mkdir(parents=True)
        (generation_root / "migrations").mkdir()
        (generation_root / "backups").mkdir()
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
        with self.assertRaisesRegex(self.artifact.ArtifactError, "not verified"):
            self.runtime.resolve_runtime_binding(
                registry_root=registry,
                generation_root=generation_root,
                manifest=self._pinned_manifest(),
            )

        (installed.path / "apps/web/out/index.html").write_text("tampered", encoding="utf-8")
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
            environment = self.launcher._daemon_env(
                data_dir=self.root / "data",
                media_config_dir=self.root / "data/media-config",
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
            "apps/daemon/package.json": '{"name":"@open-design/daemon","version":"0.16.1"}\n',
            "apps/daemon/dist/cli.js": "process.exit(0);\n",
            "apps/daemon/node_modules/.modules.yaml": "layoutVersion: 5\n",
            "apps/web/out/index.html": "<!doctype html><title>OpenDesign</title>\n",
            "maverick/build.json": '{"schema_version":"1"}\n',
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
