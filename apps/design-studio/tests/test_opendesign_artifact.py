from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
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


class OpenDesignArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = _load_module("opendesign_artifact", SERVICE_ROOT / "opendesign_artifact.py")
        cls.archive = _load_module("opendesign_archive", SERVICE_ROOT / "opendesign_archive.py")
        cls.attestation = _load_module(
            "opendesign_attestation",
            SERVICE_ROOT / "opendesign_attestation.py",
        )

    def setUp(self) -> None:
        self.manifest = self.artifact.read_bundle_manifest(MANIFEST_PATH)

    def test_manifest_contains_real_release_pins_and_rejects_missing_assets(self) -> None:
        self.artifact.validate_bundle_manifest(self.manifest, require_artifact_digest=False)
        self.artifact.validate_bundle_manifest(self.manifest, require_artifact_digest=True)

        missing_asset = copy.deepcopy(self.manifest)
        missing_asset["artifact"]["assets"][self.artifact.platform_key()]["sha256"] = None
        with self.assertRaisesRegex(self.artifact.ArtifactError, "is not pinned"):
            self.artifact.validate_bundle_manifest(missing_asset, require_artifact_digest=True)

        tampered = copy.deepcopy(self.manifest)
        tampered["upstream"]["commit"] = "0" * 40
        with self.assertRaisesRegex(self.artifact.ArtifactError, "reviewed pin"):
            self.artifact.validate_bundle_manifest(tampered, require_artifact_digest=False)

    def test_platform_aliases_and_unsupported_platform_fail_closed(self) -> None:
        self.assertEqual(self.artifact.platform_key(system="Linux", machine="amd64"), "linux-x86_64")
        self.assertEqual(self.artifact.platform_key(system="Darwin", machine="aarch64"), "darwin-arm64")
        with self.assertRaisesRegex(self.artifact.ArtifactError, "Unsupported"):
            self.artifact.platform_key(system="Plan9", machine="mips")

    def test_file_manifest_and_archive_are_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-archive-") as temp_dir:
            root = Path(temp_dir)
            stage = root / "stage"
            executable = stage / "bin/od"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            (stage / "share").mkdir()
            (stage / "share/readme.txt").write_text("OpenDesign\n", encoding="utf-8")
            (stage / "current").symlink_to("bin/od")
            manifest = self.archive.create_file_manifest(
                stage,
                exclude={self.archive.FILE_MANIFEST_PATH},
            )
            self.artifact.write_canonical_json(stage / self.archive.FILE_MANIFEST_PATH, manifest)

            self.assertEqual(self.archive.verify_file_manifest(stage), manifest)
            first = root / "first.tar.gz"
            second = root / "second.tar.gz"
            self.archive.write_deterministic_archive(stage, first)
            self.archive.write_deterministic_archive(stage, second)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(self.artifact.sha256_file(first), self.artifact.sha256_file(second))
            with tarfile.open(first, mode="r:gz") as bundle:
                members = self.archive.validated_archive_members(bundle)
            self.assertIn("bin/od", {member.name for member in members})
            self.assertEqual(
                executable.stat().st_mode & 0o777,
                stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
            )

            manifest_sha256 = self.artifact.sha256_file(stage / self.archive.FILE_MANIFEST_PATH)
            marker = {
                "schema_version": "2",
                "artifact_sha256": "a" * 64,
                "file_manifest_sha256": manifest_sha256,
                "opendesign_version": "0.16.1",
                "upstream_commit": "b" * 40,
            }
            self.artifact.write_canonical_json(stage / self.archive.MATERIALIZED_MARKER_PATH, marker)
            self.assertEqual(
                self.archive.verify_materialized_bundle(
                    stage,
                    expected_artifact_sha256="a" * 64,
                    expected_file_manifest_sha256=manifest_sha256,
                    expected_version="0.16.1",
                ),
                marker,
            )

    def test_unsafe_symlinks_and_archive_members_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-paths-") as temp_dir:
            stage = Path(temp_dir) / "stage"
            stage.mkdir()
            (stage / "escape").symlink_to("../../outside")
            with self.assertRaisesRegex(self.artifact.ArtifactError, "escapes"):
                self.archive.create_file_manifest(stage)

        for member in (
            tarfile.TarInfo("../escape"),
            tarfile.TarInfo("/absolute"),
        ):
            member.type = tarfile.REGTYPE
            with self.subTest(name=member.name):
                with self.assertRaisesRegex(self.artifact.ArtifactError, "Unsafe"):
                    self.archive.validate_archive_member(member)
        hardlink = tarfile.TarInfo("safe")
        hardlink.type = tarfile.LNKTYPE
        with self.assertRaisesRegex(self.artifact.ArtifactError, "Unsupported"):
            self.archive.validate_archive_member(hardlink)

    def test_sbom_license_notice_and_provenance_are_deterministic(self) -> None:
        packages = [
            {"name": "z-package", "version": "2.0.0", "license": "NOASSERTION"},
            {"name": "@scope/a", "version": "1.0.0", "license": "MIT"},
        ]
        sbom = self.attestation.cyclonedx_sbom(packages, version="0.16.1")
        licenses = self.attestation.license_inventory(packages, upstream=self.manifest["upstream"])
        notice = self.attestation.notice_text(licenses)
        provenance = self.attestation.provenance_payload(
            artifact_name="open-design.tar.gz",
            artifact_sha256="a" * 64,
            lockfile_sha256="b" * 64,
            patch_evidence=[{"path": "boundary.patch", "sha256": "c" * 64}],
            manifest=self.manifest,
        )

        self.assertEqual(sbom["bomFormat"], "CycloneDX")
        self.assertEqual(sbom["components"][0]["purl"], "pkg:npm/%40scope/a@1.0.0")
        self.assertEqual(licenses["declared_license_counts"], {"MIT": 1, "NOASSERTION": 1})
        self.assertIn("@scope/a@1.0.0: MIT", notice)
        self.assertEqual(provenance["subject"][0]["digest"]["sha256"], "a" * 64)
        self.assertTrue(provenance["predicate"]["runDetails"]["metadata"]["reproducible"])

    def test_runtime_package_inventory_is_sorted_and_defaults_unknown_licenses(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-packages-") as temp_dir:
            stage = Path(temp_dir)
            first = stage / "node_modules/z/package.json"
            second = stage / "node_modules/a/package.json"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_text('{"name":"z","version":"2.0.0"}', encoding="utf-8")
            second.write_text(
                '{"name":"a","version":"1.0.0","license":"Apache-2.0"}',
                encoding="utf-8",
            )

            self.assertEqual(
                self.attestation.package_inventory(stage),
                [
                    {"name": "a", "version": "1.0.0", "license": "Apache-2.0"},
                    {"name": "z", "version": "2.0.0", "license": "NOASSERTION"},
                ],
            )

    def test_signed_artifact_set_verifies_and_tampering_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-attestation-") as temp_dir:
            root = Path(temp_dir)
            manifest = copy.deepcopy(self.manifest)
            asset = manifest["artifact"]["assets"][self.artifact.platform_key()]
            archive_path = root / asset["file"]
            archive_path.write_bytes(b"deterministic artifact bytes")
            self.artifact.write_canonical_json(
                root / asset["file_manifest"],
                {"schema_version": "1", "self_excluded": ["maverick/manifest.json"], "files": []},
            )
            sbom = self.attestation.cyclonedx_sbom([], version="0.16.1")
            licenses = self.attestation.license_inventory([], upstream=manifest["upstream"])
            self.artifact.write_canonical_json(root / asset["sbom"], sbom)
            self.artifact.write_canonical_json(root / asset["license_inventory"], licenses)
            (root / asset["notice"]).write_text(self.attestation.notice_text(licenses), encoding="utf-8")
            provenance = self.attestation.provenance_payload(
                artifact_name=asset["file"],
                artifact_sha256=self.artifact.sha256_file(archive_path),
                lockfile_sha256="b" * 64,
                patch_evidence=[],
                manifest=manifest,
            )
            provenance_path = root / asset["provenance"]
            self.artifact.write_canonical_json(provenance_path, provenance)
            private_key = root / "private.pem"
            generated = subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_key)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            self.attestation.sign_provenance(
                provenance_path,
                private_key,
                root / asset["signature"],
                root / asset["public_key"],
            )
            for path_field, digest_field in self.artifact.ARTIFACT_DIGEST_FIELDS.items():
                asset[digest_field] = self.artifact.sha256_file(root / asset[path_field])
            asset["size_bytes"] = archive_path.stat().st_size

            self.assertEqual(self.attestation.verify_artifact_set(manifest, root), asset)
            (root / asset["notice"]).write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(self.artifact.ArtifactError, "digest mismatch"):
                self.attestation.verify_artifact_set(manifest, root)

    def test_duplicate_json_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-od-json-") as temp_dir:
            path = Path(temp_dir) / "duplicate.json"
            path.write_text('{"schema_version":"1","schema_version":"2"}', encoding="utf-8")
            with self.assertRaisesRegex(self.artifact.ArtifactError, "duplicate JSON field"):
                self.artifact.read_bundle_manifest(path)


if __name__ == "__main__":
    unittest.main()
