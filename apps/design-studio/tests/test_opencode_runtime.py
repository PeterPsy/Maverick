"""Pinned technical OpenCode runtime installation proofs."""

from __future__ import annotations

from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from opencode_runtime import (  # noqa: E402
    OpenCodeRuntimeError,
    OpenCodeRuntimeSpec,
    install_opencode_runtime,
    verify_opencode_runtime,
)


class OpenCodeRuntimeTests(unittest.TestCase):
    def test_digest_pinned_package_installs_and_tampering_fails_closed(self) -> None:
        binary = b"technical-opencode-fixture"
        archive = _package(binary, version="test-version")
        spec = OpenCodeRuntimeSpec(
            version="test-version",
            package="opencode-linux-x64",
            url="https://registry.npmjs.org/fixture.tgz",
            archive_size=len(archive),
            archive_sha256=sha256(archive).hexdigest(),
            binary_size=len(binary),
            binary_sha256=sha256(binary).hexdigest(),
        )
        with tempfile.TemporaryDirectory() as temporary:
            namespace = Path(temporary)
            installed = install_opencode_runtime(
                namespace,
                spec=spec,
                open_url=lambda _url: io.BytesIO(archive),
            )
            self.assertEqual(installed.read_bytes(), binary)
            self.assertTrue(installed.stat().st_mode & 0o111)
            self.assertEqual(verify_opencode_runtime(installed.parents[1], spec=spec), installed)

            installed.chmod(0o755)
            installed.write_bytes(b"tampered")
            with self.assertRaises(OpenCodeRuntimeError):
                verify_opencode_runtime(installed.parents[1], spec=spec)


def _package(binary: bytes, *, version: str) -> bytes:
    output = io.BytesIO()
    manifest = json.dumps({"name": "opencode-linux-x64", "version": version}).encode()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, body, mode in (
            ("package/package.json", manifest, 0o644),
            ("package/bin/opencode", binary, 0o755),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(body)
            member.mode = mode
            archive.addfile(member, io.BytesIO(body))
    return output.getvalue()


if __name__ == "__main__":
    unittest.main()
