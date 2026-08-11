from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


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


class OpenDesignSupplyChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.supply = _load_module(
            "opendesign_supply_chain",
            SERVICE_ROOT / "opendesign_supply_chain.py",
        )
        cls.certify = _load_module(
            "certify_opendesign_upstream",
            SERVICE_ROOT / "certify_opendesign_upstream.py",
        )

    def setUp(self) -> None:
        self.manifest = self.supply.read_json(MANIFEST_PATH)

    def test_pinned_manifest_patch_inventory_and_certification_are_consistent(self) -> None:
        self.supply.validate_manifest(self.manifest)
        series = self.supply.validate_patch_series(SERVICE_ROOT, self.manifest)
        record = self.supply.validate_certification_record(SERVICE_ROOT, self.manifest)

        files = {
            item["path"]
            for patch in series["patches"]
            for item in patch["files"]
        }
        self.assertEqual(
            files,
            {
                "apps/daemon/src/server.ts",
                "apps/daemon/tests/api-token-guard.test.ts",
                "apps/web/app/layout.tsx",
                "apps/web/src/App.tsx",
                "apps/web/next.config.ts",
                "apps/web/src/index.css",
                "package.json",
            },
        )
        self.assertEqual(record["latest_acceptance"]["status"], "pending_recertification")
        self.assertFalse(record["cancelled_workflow_diagnostic"]["resume_allowed"])

    def test_normal_packaging_rejects_pathological_suite_orchestration(self) -> None:
        for fragment in ("--shard=1/433", "--retry=2", "checkpoint", "deferred_shards"):
            tampered = copy.deepcopy(self.manifest)
            tampered["fallback_build"]["build"]["host_workaround"] = fragment
            with self.subTest(fragment=fragment):
                with self.assertRaisesRegex(self.supply.SupplyChainError, "certification orchestration"):
                    self.supply.validate_manifest(tampered)

    def test_certification_record_digest_is_fail_closed(self) -> None:
        tampered = copy.deepcopy(self.manifest)
        tampered["certification"]["record_sha256"] = "0" * 64
        with self.assertRaisesRegex(self.supply.SupplyChainError, "SHA-256 does not match"):
            self.supply.validate_certification_record(SERVICE_ROOT, tampered)

    def test_certification_plan_has_two_unsharded_single_worker_suites(self) -> None:
        plan = self.certify.certification_plan(MANIFEST_PATH)
        commands = plan["commands"]
        self.assertEqual(set(commands), {"install", "web", "daemon"})
        self.assertEqual(commands["install"][-1], "--frozen-lockfile")
        for suite in ("web", "daemon"):
            command = commands[suite]
            self.assertIn("--maxWorkers=1", command)
            encoded = " ".join(command)
            self.assertNotIn("--shard", encoded)
            self.assertNotIn("--retry", encoded)
            self.assertNotIn("--exclude", encoded)
            self.assertNotIn("--testNamePattern", encoded)

    def test_source_identity_checks_tag_commit_packages_and_cleanliness(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-source-id-") as temp_dir:
            source = Path(temp_dir)
            release = source / "apps/packaged/package.json"
            release.parent.mkdir(parents=True)
            release.write_text(
                json.dumps({"name": "@open-design/packaged", "version": "0.16.1"}),
                encoding="utf-8",
            )
            (source / "package.json").write_text(
                json.dumps(
                    {
                        "version": "0.15.1",
                        "packageManager": "pnpm@10.33.2",
                    }
                ),
                encoding="utf-8",
            )
            commit = self.manifest["upstream"]["commit"]

            def fake_run(command, **kwargs):
                del kwargs
                if command[-3:] == ["status", "--porcelain", "--untracked-files=no"]:
                    output = ""
                else:
                    output = f"{commit}\n"
                return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

            self.supply.validate_source_identity(source, self.manifest, run=fake_run)

    def test_source_identity_rejects_a_different_head(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-source-id-") as temp_dir:
            source = Path(temp_dir)

            def fake_run(command, **kwargs):
                del kwargs
                return subprocess.CompletedProcess(command, 0, stdout=f"{'0' * 40}\n", stderr="")

            with self.assertRaisesRegex(self.supply.SupplyChainError, "HEAD or tag"):
                self.supply.validate_source_identity(source, self.manifest, run=fake_run)

if __name__ == "__main__":
    unittest.main()
