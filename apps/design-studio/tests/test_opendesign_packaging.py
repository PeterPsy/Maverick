"""Focused tests for the bounded OpenDesign build workflow."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
MANIFEST_PATH = SERVICE_ROOT / "opendesign_bundle.json"


def _load_module(name: str, path: Path):
    sys.path.insert(0, str(SERVICE_ROOT))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class OpenDesignPackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = _load_module("opendesign_artifact", SERVICE_ROOT / "opendesign_artifact.py")
        cls.process = _load_module("opendesign_process", SERVICE_ROOT / "opendesign_process.py")
        cls.source = _load_module("opendesign_source", SERVICE_ROOT / "opendesign_source.py")
        cls.stage = _load_module("opendesign_stage", SERVICE_ROOT / "opendesign_stage.py")
        cls.build = _load_module("opendesign_build", SERVICE_ROOT / "opendesign_build.py")
        cls.packager = _load_module("package_opendesign", SERVICE_ROOT / "package_opendesign.py")

    def setUp(self) -> None:
        self.manifest = self.artifact.read_bundle_manifest(MANIFEST_PATH)

    def test_memavailable_policy_uses_four_gib_start_and_two_point_four_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-memory-") as temp_dir:
            meminfo = Path(temp_dir) / "meminfo"
            meminfo.write_text(
                "MemTotal: 8388608 kB\nMemFree: 1 kB\nMemAvailable: 4194304 kB\n",
                encoding="utf-8",
            )
            snapshot = self.process.host_memory_snapshot(meminfo)
            self.assertEqual(snapshot.available_bytes, 4 * 1024**3)
            self.assertEqual(self.process.START_AVAILABLE_BYTES, 4 * 1024**3)
            self.assertEqual(self.process.STOP_AVAILABLE_BYTES, int(2.4 * 1024**3))
            self.assertLessEqual(self.process.START_WAIT_SECONDS, 60)

    def test_memory_wait_is_bounded_and_never_raises_the_threshold(self) -> None:
        low = self.process.HostMemorySnapshot(8 * 1024**3, 3 * 1024**3)
        with self.assertRaisesRegex(self.process.BuildProcessError, "timed out"):
            self.process.wait_for_start_capacity(
                snapshot_reader=lambda: low,
                sleeper=lambda _seconds: None,
                timeout_seconds=0,
            )

    def test_compile_heap_is_bounded_without_changing_host_thresholds(self) -> None:
        self.assertEqual(
            self.manifest["fallback_build"]["build"]["compile_environment"]["NODE_OPTIONS"],
            "--max-old-space-size=1536",
        )
        self.assertEqual(self.process.START_AVAILABLE_BYTES, 4 * 1024**3)

    def test_runtime_attachment_requires_the_matching_codex_ancestor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-proc-") as temp_dir:
            proc = Path(temp_dir)
            child = proc / "20"
            parent = proc / "10"
            child.mkdir()
            parent.mkdir()
            (child / "environ").write_bytes(b"PATH=/bin\0")
            (child / "cmdline").write_bytes(b"bash\0")
            (child / "status").write_text("PPid:\t10\n", encoding="utf-8")
            (parent / "environ").write_bytes(b"MAVERICK_RUNTIME_SESSION_ID=session-1\0")
            (parent / "cmdline").write_bytes(b"codex\0app-server\0")
            (parent / "status").write_text("PPid:\t1\n", encoding="utf-8")

            self.assertTrue(
                self.process.runtime_session_is_in_ancestry(
                    "session-1",
                    parent_pid=20,
                    proc_root=proc,
                )
            )
            self.assertFalse(
                self.process.runtime_session_is_in_ancestry(
                    "different",
                    parent_pid=20,
                    proc_root=proc,
                )
            )

    def test_process_runner_uses_a_process_group_and_captures_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-command-") as temp_dir:
            result = self.process.run_command(
                [sys.executable, "-c", "print('bounded')"],
                cwd=Path(temp_dir),
                capture=True,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "bounded")

    def test_build_environment_is_credential_free_and_uses_the_owned_store(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-env-") as temp_dir:
            root = Path(temp_dir)
            with patch.dict(os.environ, {"SECRET_SENTINEL": "must-not-leak"}, clear=False):
                environment = self.build.build_environment(
                    root / "result",
                    tool_bin=root / "tools",
                    manifest=self.manifest,
                    pnpm_store=root / "store",
                )
            self.assertNotIn("SECRET_SENTINEL", environment)
            self.assertEqual(environment["npm_config_store_dir"], str(root / "store"))
            self.assertEqual(environment["HOME"], str(root / "result/home"))

    def test_build_environment_rejects_a_tmpdir_that_cannot_host_unix_sockets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-env-") as temp_dir:
            root = Path(temp_dir)
            long_result = root / ("long-segment-" * 8)
            with self.assertRaisesRegex(self.build.BuildError, "Unix sockets"):
                self.build.build_environment(
                    long_result,
                    tool_bin=root / "tools",
                    manifest=self.manifest,
                    pnpm_store=root / "store",
                )

    def test_bin_shim_normalization_removes_build_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-shim-") as temp_dir:
            staging = Path(temp_dir) / "staging"
            daemon = staging / "apps/daemon"
            shim = daemon / "node_modules/example/.bin/tool"
            shim.parent.mkdir(parents=True)
            shim.write_text(
                "#!/bin/sh\n"
                "basedir=$(dirname \"$0\")\n"
                f"  export NODE_PATH=\"{staging}/apps/daemon/node_modules\"\n"
                "exec node tool.js\n",
                encoding="utf-8",
            )
            shim.chmod(0o755)

            normalized = self.stage._normalize_bin_shims(staging, daemon)

            self.assertEqual(normalized, ["apps/daemon/node_modules/example/.bin/tool"])
            self.assertNotIn(str(staging), shim.read_text(encoding="utf-8"))
            self.stage._reject_build_path_leaks(staging, markers=(str(staging),))

    def test_source_export_from_a_bare_repository_is_clean_and_exact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-source-") as temp_dir:
            root = Path(temp_dir)
            checkout = root / "checkout"
            bare = root / "source.git"
            exported = root / "exported"
            checkout.mkdir()
            self._git(checkout, "init")
            self._git(checkout, "config", "user.email", "test@example.invalid")
            self._git(checkout, "config", "user.name", "Test")
            (checkout / "apps/packaged").mkdir(parents=True)
            (checkout / "apps/packaged/package.json").write_text(
                '{"name":"@open-design/packaged","version":"0.16.1"}',
                encoding="utf-8",
            )
            (checkout / "package.json").write_text(
                '{"version":"0.15.1","packageManager":"pnpm@10.33.2"}',
                encoding="utf-8",
            )
            (checkout / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
            self._git(checkout, "add", "apps/packaged/package.json", "package.json", "pnpm-lock.yaml")
            self._git(checkout, "commit", "-m", "fixture")
            commit = self._git(checkout, "rev-parse", "HEAD").stdout.strip()
            self._git(checkout, "tag", "fixture-v1")
            cloned = subprocess.run(
                ["git", "clone", "--bare", str(checkout), str(bare)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(cloned.returncode, 0, cloned.stderr)
            manifest = copy.deepcopy(self.manifest)
            manifest["upstream"]["commit"] = commit
            manifest["upstream"]["tag"] = "fixture-v1"
            manifest["upstream"]["tag_metadata"] = {
                "object_type": "commit",
                "signature": "unavailable",
                "reason": "fixture",
            }

            evidence = self.source.export_source(bare, exported, manifest)

            self.assertEqual(evidence["commit"], commit)
            self.assertTrue((exported / "pnpm-lock.yaml").is_file())
            self.assertFalse((exported / ".git").exists())

    def test_packager_runs_exactly_two_builds_and_publishes_verified_pins(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-package-") as temp_dir:
            root = Path(temp_dir)
            repository = root / "source.git"
            repository.mkdir()
            signing_key = root / "private.pem"
            generated = subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(signing_key)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            calls: list[int] = []

            def fake_build(_repository, result_root, **kwargs):
                del _repository, kwargs
                calls.append(len(calls) + 1)
                return self._fixture_build_result(result_root)

            with patch.object(self.packager, "validate_repository", return_value={"commit": "pinned"}):
                result = self.packager.build_reproducible_artifact(
                    repository,
                    root / "output",
                    signing_key=signing_key,
                    manifest=self.manifest,
                    work_parent=root / "work",
                    pnpm_store=root / "store",
                    runtime_session_id=None,
                    build_function=fake_build,
                )

            self.assertEqual(calls, [1, 2])
            self.assertEqual(result["build_artifact_sha256s"], [result["artifact_sha256"]] * 2)
            self.assertGreater(result["artifact_size_bytes"], 0)
            self.assertTrue(all(value is not None for value in result["artifact_pins"].values()))

    def test_production_packager_has_no_upstream_matrix_or_resume_framework(self) -> None:
        paths = [
            SERVICE_ROOT / "package_opendesign.py",
            SERVICE_ROOT / "opendesign_build.py",
            SERVICE_ROOT / "opendesign_process.py",
            SERVICE_ROOT / "opendesign_stage.py",
        ]
        source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        for forbidden in (
            "verification_checkpoint",
            "web_shard_count",
            "daemon_shard_count",
            "deferred_shards",
            "release-57",
            "testNamePattern",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertNotIn("certify_opendesign_upstream", (SERVICE_ROOT / "package_opendesign.py").read_text())

    def _fixture_build_result(self, result_root: Path):
        result_root.mkdir(exist_ok=True)
        artifact_path = result_root / "open-design-v0.16.1-linux-x86_64.tar.gz"
        artifact_path.write_bytes(b"byte-identical-artifact")
        metadata = result_root / "metadata"
        metadata.mkdir()
        file_manifest = {"schema_version": "1", "self_excluded": [], "files": []}
        (metadata / "file-manifest.json").write_text(
            json.dumps(file_manifest, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (metadata / "sbom.cdx.json").write_text(
            '{"bomFormat":"CycloneDX","specVersion":"1.6","version":1}\n',
            encoding="utf-8",
        )
        (metadata / "licenses.json").write_text(
            '{"schema_version":"1","root_license":"Apache-2.0","packages":[]}\n',
            encoding="utf-8",
        )
        (metadata / "NOTICE").write_text("OpenDesign notice\n", encoding="utf-8")
        (metadata / "build.json").write_text('{"schema_version":"1"}\n', encoding="utf-8")
        digest = self.artifact.sha256_file(artifact_path)
        return self.build.BuildResult(
            artifact=artifact_path,
            artifact_sha256=digest,
            artifact_size_bytes=artifact_path.stat().st_size,
            file_manifest=file_manifest,
            file_manifest_path=metadata / "file-manifest.json",
            sbom_path=metadata / "sbom.cdx.json",
            licenses_path=metadata / "licenses.json",
            notice_path=metadata / "NOTICE",
            build_metadata_path=metadata / "build.json",
            source_evidence={"commit": "pinned"},
            patch_evidence=[],
            lockfile_sha256="b" * 64,
        )

    def _git(self, cwd: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed


if __name__ == "__main__":
    unittest.main()
