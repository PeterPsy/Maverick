"""Protected OpenDesign store, manifest-v2, repair, and crash-safety tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import errno
import json
import os
from pathlib import Path
import select
import shutil
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_archive import FILE_MANIFEST_PATH, create_file_manifest, write_deterministic_archive  # noqa: E402
from opendesign_artifact import sha256_file, write_canonical_json  # noqa: E402
from opendesign_artifact_store import (  # noqa: E402
    ArtifactStoreError,
    OpenDesignArtifactStore,
    _mapped_namespace_id,
)
from opendesign_store_manifest import (  # noqa: E402
    StoreManifestError,
    create_store_manifest,
    manifest_sha256,
    verify_store_manifest,
)
from opendesign_artifact_operations import (  # noqa: E402
    RequiredArtifacts,
    _clear_invalid_marker,
    _garbage_collect,
    _known_invalid_identity,
    _mark_invalid,
    _purge_expired_quarantine,
    _required_artifacts,
)


UPSTREAM_COMMIT = "b" * 40


class OpenDesignArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="maverick-od-store-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.namespace = self.root / "platform-store/design-studio/opendesign"
        self.namespace.mkdir(parents=True, mode=0o750)
        self.namespace.chmod(0o750)
        write_canonical_json(
            self.namespace / ".maverick-artifact-namespace.json",
            {
                "schema_version": "1",
                "app_id": "design-studio",
                "artifact_id": "opendesign",
                "store_generation": "1" * 32,
                "owner_uid": os.geteuid(),
                "owner_gid": os.getegid(),
            },
        )
        (self.namespace / ".maverick-artifact-namespace.json").chmod(0o640)
        self.store = OpenDesignArtifactStore(self.namespace)
        self.archive_path, self.archive_digest, self.source_manifest_digest = self._runtime_archive()

    def test_release_retention_declares_a_runtime_overlay_rollback_pair(self) -> None:
        manifest = json.loads((SERVICE_ROOT / "opendesign_bundle.json").read_text(encoding="utf-8"))
        selection = json.loads(
            (SERVICE_ROOT / "opendesign_release_selection.json").read_text(encoding="utf-8")
        )

        required = _required_artifacts(self.root / "fresh-data", manifest=manifest)

        self.assertEqual(selection["schema_version"], "3")
        self.assertEqual(
            required.rollback_runtime,
            selection["rollback_runtime_artifact_sha256"],
        )
        self.assertIn(selection["rollback_web_overlay_sha256"], required.web_overlays)
        self.assertNotIn(required.rollback_runtime, required.optional_runtime)

    def test_release_retention_rejects_current_runtime_as_rollback(self) -> None:
        manifest = json.loads((SERVICE_ROOT / "opendesign_bundle.json").read_text(encoding="utf-8"))
        current = manifest["artifact"]["assets"]["linux-x86_64"]["sha256"]
        with patch(
            "opendesign_artifact_operations._read_selection",
            return_value={
                "schema_version": "3",
                "active_web_overlay_sha256": "a" * 64,
                "rollback_runtime_artifact_sha256": current,
                "rollback_web_overlay_sha256": "b" * 64,
                "runtime_source_catalog_sha256": "c" * 64,
                "quarantine_retention_days": 14,
            },
        ):
            with self.assertRaisesRegex(ArtifactStoreError, "rollback runtime"):
                _required_artifacts(self.root / "fresh-data", manifest=manifest)

    def test_host_owner_is_translated_into_the_current_user_namespace(self) -> None:
        mapping = self.root / "uid_map"
        mapping.write_text("         0       1000          1\n", encoding="ascii")
        self.assertEqual(_mapped_namespace_id(1000, mapping), 0)
        self.assertEqual(_mapped_namespace_id(1001, mapping), 1001)

    def test_manifest_v2_detects_modes_directories_symlinks_content_and_inventory_drift(self) -> None:
        content = self.root / "manifest-content"
        self._manifest_content(content)
        expected = create_store_manifest(content)
        self.assertIn("directory", {entry["kind"] for entry in expected["entries"]})
        self.assertEqual(verify_store_manifest(content, expected), expected)
        self.assertEqual(verify_store_manifest(content, expected, max_workers=1), expected)
        with self.assertRaisesRegex(StoreManifestError, "worker limit"):
            create_store_manifest(content, max_workers=0)

        mutations = {
            "0644-to-0664": lambda root: (root / "share/readme.txt").chmod(0o664),
            "0755-to-0775": lambda root: (root / "bin/od").chmod(0o775),
            "directory-mode": lambda root: (root / "share").chmod(0o775),
            "symlink-target": self._alter_symlink,
            "extra-file": lambda root: (root / "extra.txt").write_text("extra", encoding="utf-8"),
            "missing-file": lambda root: (root / "share/readme.txt").unlink(),
            "content": lambda root: (root / "share/readme.txt").write_text("changed", encoding="utf-8"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                candidate = self.root / f"candidate-{name}"
                shutil.copytree(content, candidate, symlinks=True)
                mutate(candidate)
                with self.assertRaises(StoreManifestError) as raised:
                    verify_store_manifest(candidate, expected)
                self.assertGreaterEqual(raised.exception.differences, 1)

    def test_fast_receipt_path_does_not_hash_content_and_full_audit_detects_tampering(self) -> None:
        published = self._publish_runtime()
        executable = published.content_path / "bin/od"
        executable.chmod(0o775)

        fast = self.store.fast_runtime(
            self.archive_digest,
            file_manifest_sha256=self.source_manifest_digest,
            opendesign_version="0.16.1",
            upstream_commit=UPSTREAM_COMMIT,
        )
        self.assertEqual(fast.content_path, published.content_path)
        with self.assertRaises(ArtifactStoreError) as raised:
            self.store.full_audit("runtime", self.archive_digest)
        self.assertEqual(raised.exception.code, "artifact_integrity_mismatch")
        self.assertGreaterEqual(raised.exception.differences, 1)

    def test_receipt_authenticates_manifest_v2_on_fast_and_full_paths(self) -> None:
        published = self._publish_runtime()
        receipt_digest = published.receipt["file_manifest_sha256"]
        (published.content_path / "share/readme.txt").write_text("replacement\n", encoding="utf-8")
        replacement_manifest = create_store_manifest(published.content_path)
        self.assertNotEqual(manifest_sha256(replacement_manifest), receipt_digest)
        write_canonical_json(published.package_path / "manifest-v2.json", replacement_manifest)

        with self.assertRaises(ArtifactStoreError) as fast_failure:
            self.store.fast_runtime(
                self.archive_digest,
                file_manifest_sha256=self.source_manifest_digest,
                opendesign_version="0.16.1",
                upstream_commit=UPSTREAM_COMMIT,
            )
        self.assertEqual(fast_failure.exception.phase, "artifact_fast_verify")

        # Even if the file changes after the fast digest read, full audit binds
        # the parsed manifest to the same receipt before trusting its inventory.
        with (
            patch("opendesign_artifact_store.sha256_file", return_value=receipt_digest),
            self.assertRaises(ArtifactStoreError) as full_failure,
        ):
            self.store.full_audit("runtime", self.archive_digest)
        self.assertEqual(full_failure.exception.phase, "artifact_full_verify")
        self.assertGreaterEqual(full_failure.exception.differences, 1)

    def test_receipt_tampering_fails_fast_and_repair_quarantines_instead_of_editing_in_place(self) -> None:
        published = self._publish_runtime()
        receipt_path = published.package_path / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["store_generation"] = "2" * 32
        write_canonical_json(receipt_path, receipt)
        receipt_path.chmod(0o640)

        with self.assertRaises(ArtifactStoreError) as raised:
            self.store.fast_runtime(
                self.archive_digest,
                file_manifest_sha256=self.source_manifest_digest,
                opendesign_version="0.16.1",
                upstream_commit=UPSTREAM_COMMIT,
            )
        self.assertEqual(raised.exception.phase, "artifact_fast_verify")

        repaired = self._publish_runtime(repair=True)
        self.store.full_audit("runtime", self.archive_digest)
        quarantine = list((self.namespace / "quarantine/runtime").iterdir())
        self.assertEqual(len(quarantine), 1)
        self.assertNotEqual(repaired.package_path.stat().st_ino, quarantine[0].stat().st_ino)

    def test_full_audit_handoff_replaces_only_the_same_invalid_inode(self) -> None:
        published = self._publish_runtime()
        (published.content_path / "share/readme.txt").write_text("tampered", encoding="utf-8")
        with self.assertRaises(ArtifactStoreError):
            self.store.full_audit("runtime", self.archive_digest)
        _mark_invalid(self.store, kind="runtime", digest=self.archive_digest)
        identity = _known_invalid_identity(self.store, kind="runtime", digest=self.archive_digest)
        self.assertEqual(identity, self.store.package_identity("runtime", self.archive_digest))
        with self.assertRaises(ArtifactStoreError) as rejected:
            self.store.fast_runtime(
                self.archive_digest,
                file_manifest_sha256=self.source_manifest_digest,
                opendesign_version="0.16.1",
                upstream_commit=UPSTREAM_COMMIT,
            )
        self.assertEqual(rejected.exception.code, "artifact_integrity_mismatch")
        self.assertEqual(rejected.exception.phase, "artifact_fast_verify")

        with patch.object(self.store, "full_audit", side_effect=AssertionError("duplicate audit")):
            repaired = self._publish_to(
                self.store,
                repair=True,
                invalid_package_identity=identity,
            )
        self.assertNotEqual(identity, self.store.package_identity("runtime", self.archive_digest))
        self.assertIsNone(_known_invalid_identity(self.store, kind="runtime", digest=self.archive_digest))
        _clear_invalid_marker(self.store, kind="runtime", digest=self.archive_digest)
        self.assertEqual(repaired.artifact_sha256, self.archive_digest)

    def test_concurrent_repairs_singleflight_through_digest_lock(self) -> None:
        published = self._publish_runtime()
        (published.content_path / "share/readme.txt").write_text("tampered", encoding="utf-8")

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: self._publish_runtime(repair=True), range(2)))

        self.assertEqual({result.artifact_sha256 for result in results}, {self.archive_digest})
        self.assertEqual(len(list((self.namespace / "quarantine/runtime").iterdir())), 1)
        self.store.full_audit("runtime", self.archive_digest)

    def test_failure_injection_never_exposes_partial_active_package_and_repair_resumes(self) -> None:
        for phase in ("extraction", "full_verify", "receipt", "fsync"):
            with self.subTest(phase=phase):
                isolated = self.root / f"store-{phase}"
                shutil.copytree(self.namespace, isolated)
                store = OpenDesignArtifactStore(isolated)
                with self.assertRaisesRegex(RuntimeError, phase):
                    self._publish_to(store, injector=lambda current, target=phase: self._crash(current, target))
                self.assertFalse((isolated / "runtime" / self.archive_digest).exists())

        published = self._publish_runtime()
        (published.content_path / "share/readme.txt").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "quarantine"):
            self._publish_runtime(
                repair=True,
                injector=lambda current: self._crash(current, "quarantine"),
            )
        self.assertFalse((self.namespace / "runtime" / self.archive_digest).exists())
        resumed = self._publish_runtime(repair=True)
        self.assertEqual(resumed.artifact_sha256, self.archive_digest)
        self.store.full_audit("runtime", self.archive_digest)

        rename_store_root = self.root / "store-rename"
        shutil.copytree(self.namespace, rename_store_root)
        rename_store = OpenDesignArtifactStore(rename_store_root)
        active = rename_store.root / "runtime" / self.archive_digest
        (active / "content/share/readme.txt").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "rename"):
            self._publish_to(
                rename_store,
                repair=True,
                injector=lambda current: self._crash(current, "rename"),
            )
        self.assertTrue(active.is_dir())
        rename_store.full_audit("runtime", self.archive_digest)

    @unittest.skipUnless(hasattr(os, "fork"), "requires POSIX process semantics")
    def test_sigkill_stage_is_not_reaped_live_then_is_quarantined_and_retained(self) -> None:
        read_descriptor, write_descriptor = os.pipe()
        child_pid = os.fork()
        if child_pid == 0:  # pragma: no cover - assertions are made by the parent
            os.close(read_descriptor)

            def pause_after_fsync(phase: str) -> None:
                if phase == "fsync":
                    os.write(write_descriptor, b"1")
                    while True:
                        signal.pause()

            try:
                child_store = OpenDesignArtifactStore(self.namespace)
                self._publish_to(child_store, injector=pause_after_fsync)
            finally:
                os._exit(70)

        os.close(write_descriptor)
        waited = False
        try:
            readable, _, _ = select.select([read_descriptor], [], [], 10)
            self.assertTrue(readable, "child publisher did not reach the protected fsync phase")
            self.assertEqual(os.read(read_descriptor, 1), b"1")

            while_live = self.store.recover_orphaned_staging(legacy_grace_seconds=0)
            self.assertEqual(while_live, {"recovered": 0, "active": 1, "deferred_legacy": 0})
            self.assertEqual(len(list((self.namespace / ".staging").iterdir())), 1)

            os.kill(child_pid, signal.SIGKILL)
            _pid, status = os.waitpid(child_pid, 0)
            waited = True
            self.assertTrue(os.WIFSIGNALED(status))
            self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)

            after_kill = self.store.recover_orphaned_staging(legacy_grace_seconds=0)
            self.assertEqual(after_kill, {"recovered": 1, "active": 0, "deferred_legacy": 0})
            self.assertEqual(list((self.namespace / ".staging").iterdir()), [])
            self.assertEqual(list((self.namespace / ".staging-leases").iterdir()), [])
            quarantined = list((self.namespace / "quarantine/staging").iterdir())
            self.assertEqual(len(quarantined), 1)
            self.assertFalse((self.namespace / "runtime" / self.archive_digest).exists())

            resumed = self._publish_runtime()
            self.assertEqual(resumed.artifact_sha256, self.archive_digest)
            self.store.full_audit("runtime", self.archive_digest)

            expired = time.time() - (2 * 24 * 60 * 60)
            os.utime(quarantined[0], (expired, expired))
            _purge_expired_quarantine(self.namespace, retention_days=1)
            self.assertEqual(list((self.namespace / "quarantine/staging").iterdir()), [])
        finally:
            os.close(read_descriptor)
            if not waited:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                os.waitpid(child_pid, 0)

    def test_enospc_fails_typed_cleans_stage_and_allows_a_fresh_publish(self) -> None:
        with (
            patch(
                "opendesign_artifact_store._fsync_tree",
                side_effect=OSError(errno.ENOSPC, "injected disk full"),
            ),
            self.assertRaises(ArtifactStoreError) as raised,
        ):
            self._publish_runtime()

        self.assertEqual(raised.exception.code, "artifact_repair_failed")
        self.assertEqual(raised.exception.phase, "artifact_staging")
        self.assertEqual(list((self.namespace / ".staging").iterdir()), [])
        self.assertEqual(list((self.namespace / ".staging-leases").iterdir()), [])
        self.assertFalse((self.namespace / "runtime" / self.archive_digest).exists())
        self.assertEqual(self._publish_runtime().artifact_sha256, self.archive_digest)

    def test_unleased_legacy_stage_uses_a_grace_period_before_quarantine(self) -> None:
        legacy = self.namespace / ".staging/.runtime-legacy-dead"
        legacy.mkdir()
        (legacy / "partial").write_bytes(b"partial")

        recent = self.store.recover_orphaned_staging(legacy_grace_seconds=300)
        self.assertEqual(recent, {"recovered": 0, "active": 0, "deferred_legacy": 1})
        expired = time.time() - 301
        os.utime(legacy, (expired, expired))
        recovered = self.store.recover_orphaned_staging(legacy_grace_seconds=300)
        self.assertEqual(recovered, {"recovered": 1, "active": 0, "deferred_legacy": 0})
        self.assertFalse(legacy.exists())
        self.assertEqual(len(list((self.namespace / "quarantine/staging").iterdir())), 1)

    def test_garbage_collection_recovers_orphaned_staging(self) -> None:
        orphan = self.namespace / ".staging/.runtime-legacy-gc"
        orphan.mkdir()
        expired = time.time() - 301
        os.utime(orphan, (expired, expired))
        required = RequiredArtifacts(
            current_runtime=self.archive_digest,
            active_runtime=self.archive_digest,
            rollback_runtime="a" * 64,
            active_web="b" * 64,
            optional_runtime=(),
            web_overlays=(),
            fresh_web_overlay="b" * 64,
        )

        with patch(
            "opendesign_artifact_operations._read_selection",
            return_value={"quarantine_retention_days": 14},
        ):
            result = _garbage_collect(self.store, required=required)

        self.assertEqual(
            result["staging_recovery"],
            {"recovered": 1, "active": 0, "deferred_legacy": 0},
        )
        self.assertFalse(orphan.exists())
        self.assertEqual(len(list((self.namespace / "quarantine/staging").iterdir())), 1)

    def _publish_runtime(self, *, repair: bool = False, injector=None):
        return self._publish_to(self.store, repair=repair, injector=injector)

    def _publish_to(
        self,
        store: OpenDesignArtifactStore,
        *,
        repair: bool = False,
        injector=None,
        invalid_package_identity=None,
    ):
        asset = {
            "file": self.archive_path.name,
            "sha256": self.archive_digest,
            "file_manifest_sha256": self.source_manifest_digest,
        }
        manifest = {
            "upstream": {"release_version": "0.16.1", "commit": UPSTREAM_COMMIT},
        }
        with patch("opendesign_artifact_store.verify_artifact_set", return_value=asset):
            return store.publish_runtime(
                self.archive_path.parent,
                manifest=manifest,
                repair=repair,
                invalid_package_identity=invalid_package_identity,
                failure_injector=injector,
            )

    def _runtime_archive(self) -> tuple[Path, str, str]:
        stage = self.root / "runtime-stage"
        self._manifest_content(stage)
        manifest = create_file_manifest(stage, exclude={FILE_MANIFEST_PATH})
        manifest_path = stage / FILE_MANIFEST_PATH
        write_canonical_json(manifest_path, manifest)
        archive = self.root / "runtime.tar.gz"
        write_deterministic_archive(stage, archive)
        return archive, sha256_file(archive), sha256_file(manifest_path)

    @staticmethod
    def _manifest_content(root: Path) -> None:
        executable = root / "bin/od"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)
        readme = root / "share/readme.txt"
        readme.parent.mkdir()
        readme.write_text("OpenDesign\n", encoding="utf-8")
        readme.chmod(0o644)
        (root / "current").symlink_to("bin/od")

    @staticmethod
    def _alter_symlink(root: Path) -> None:
        (root / "current").unlink()
        (root / "current").symlink_to("share/readme.txt")

    @staticmethod
    def _crash(current: str, target: str) -> None:
        if current == target:
            raise RuntimeError(target)


if __name__ == "__main__":
    unittest.main()
