"""Acceptance tests for the unchanged official OpenDesign installation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from official_opendesign_release import (  # noqa: E402
    OFFICIAL_MANIFEST_DIGEST,
    OfficialReleaseError,
    build_official_launch_command,
    load_official_release,
    snapshot_rootfs,
    verify_rootfs_snapshot,
)


def _write_minimal_rootfs(rootfs: Path) -> None:
    files = {
        "app/apps/daemon/dist/cli.js": b"console.log('daemon')\n",
        "app/apps/web/out/index.html": b"<!doctype html><title>Open Design</title>\n",
        "usr/local/bin/node": b"official-node\n",
        "lib/ld-musl-x86_64.so.1": b"official-loader\n",
        "sbin/tini": b"official-tini\n",
    }
    for relative, body in files.items():
        path = rootfs / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        if relative in {"usr/local/bin/node", "lib/ld-musl-x86_64.so.1", "sbin/tini"}:
            path.chmod(0o755)


class OfficialOpenDesignReleaseTests(unittest.TestCase):
    def test_release_descriptor_is_the_pinned_official_0_16_1_oci(self) -> None:
        release = load_official_release(SERVICE_ROOT / "opendesign_official_release.json")

        self.assertEqual(release.version, "0.16.1")
        self.assertEqual(release.manifest_digest, OFFICIAL_MANIFEST_DIGEST)
        self.assertEqual(release.reference, "0.16.1")
        self.assertEqual(release.image, "ghcr.io/nexu-io/od")
        self.assertEqual(release.command, ("node", "apps/daemon/dist/cli.js", "--no-open"))
        self.assertEqual(release.entrypoint, ("/sbin/tini", "--"))
        self.assertEqual(release.customizations, ())

    def test_release_descriptor_rejects_any_customization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            payload = json.loads((SERVICE_ROOT / "opendesign_official_release.json").read_text())
            payload["customizations"] = ["web-overlay"]
            path = Path(temporary) / "release.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(OfficialReleaseError, "customizations"):
                load_official_release(path)

    def test_rootfs_snapshot_proves_bytes_and_links_are_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rootfs = Path(temporary) / "rootfs"
            _write_minimal_rootfs(rootfs)
            (rootfs / "usr/bin").mkdir(parents=True)
            (rootfs / "usr/bin/node").symlink_to("../local/bin/node")

            snapshot = snapshot_rootfs(rootfs)
            verify_rootfs_snapshot(rootfs, snapshot)

            daemon = rootfs / "app/apps/daemon/dist/cli.js"
            daemon.write_bytes(b"modified\n")
            with self.assertRaisesRegex(OfficialReleaseError, "rootfs differs"):
                verify_rootfs_snapshot(rootfs, snapshot)

    def test_launch_command_uses_only_official_rootfs_and_disables_bridges(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rootfs = Path(temporary) / "rootfs"
            data = Path(temporary) / "data"
            _write_minimal_rootfs(rootfs)
            data.mkdir()
            release = load_official_release(SERVICE_ROOT / "opendesign_official_release.json")

            command, env = build_official_launch_command(
                release,
                rootfs=rootfs,
                data_dir=data,
                port=17456,
                api_token="disposable-token",
                bridge_mode="disabled",
            )

            rendered = " ".join(command)
            self.assertTrue(command[0].endswith("bwrap"))
            self.assertIn("--unshare-net", command)
            self.assertIn(str(rootfs), command)
            self.assertIn("/sbin/tini -- node apps/daemon/dist/cli.js --no-open", rendered)
            self.assertEqual(env["OD_DATA_DIR"], "/app/.od")
            self.assertEqual(env["OD_PORT"], "17456")
            self.assertEqual(env["OD_API_TOKEN"], "disposable-token")
            self.assertEqual(env["MAVERICK_OPENDESIGN_MODEL_BRIDGE"], "disabled")
            self.assertEqual(env["MAVERICK_OPENDESIGN_DELEGATION_BRIDGE"], "disabled")
            self.assertTrue(all("overlay" not in part.lower() and "patch" not in part.lower() for part in command))

    def test_disposable_api_uses_only_an_authenticated_unix_relay_into_the_network_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rootfs = root / "rootfs"
            data = root / "data"
            relay = root / "relay"
            _write_minimal_rootfs(rootfs)
            data.mkdir()
            relay.mkdir(mode=0o700)
            release = load_official_release(SERVICE_ROOT / "opendesign_official_release.json")
            read_fd, write_fd = os.pipe()
            os.close(write_fd)
            self.addCleanup(os.close, read_fd)

            command, _env = build_official_launch_command(
                release,
                rootfs=rootfs,
                data_dir=data,
                port=17456,
                api_token="disposable-token",
                relay_directory=relay,
                relay_secret_fd=read_fd,
            )

            rendered = " ".join(command)
            self.assertIn("--unshare-net", command)
            self.assertIn("/run/maverick-relay/api.sock", command)
            self.assertIn("maverick-sidecar-relay.py", rendered)
            self.assertIn("--target-host 127.0.0.1", rendered)
            self.assertIn("/sbin/tini -- node apps/daemon/dist/cli.js --no-open", rendered)

    def test_snapshot_digest_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rootfs = Path(temporary) / "rootfs"
            _write_minimal_rootfs(rootfs)

            first = snapshot_rootfs(rootfs)
            second = snapshot_rootfs(rootfs)

            self.assertEqual(first, second)
            canonical = json.dumps(first, sort_keys=True, separators=(",", ":")).encode()
            self.assertEqual(len(hashlib.sha256(canonical).hexdigest()), 64)


if __name__ == "__main__":
    unittest.main()
