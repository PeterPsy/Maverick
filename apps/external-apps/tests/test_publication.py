"""Deterministic storage/publication invariants; no live workspace or listener."""
from pathlib import Path
import hashlib
import io
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from external_apps.artifacts import promote, verify
from external_apps.bindings import read_binding, write_binding
from external_apps.errors import AppError
from external_apps.policy import canonical_host, canonical_path


def archive(files=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in (files or {"index.html": "<!doctype html><h1>Public</h1>"}).items():
            z.writestr(name, content)
    return stream.getvalue()


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_validated_promotion_and_tamper_denial(self):
        data = archive()
        result = promote(self.root, data, entrypoint="index.html")
        self.assertEqual(result["digest"], hashlib.sha256(data).hexdigest())
        verify(self.root / "public", result["digest"], result["manifest_digest"])
        path = self.root / "public/artifacts" / result["digest"] / "files/index.html"
        path.write_text("changed")
        with self.assertRaises(AppError):
            verify(self.root / "public", result["digest"], result["manifest_digest"])

    def test_unsafe_paths_and_private_files(self):
        for name in ("../outside.html", "/index.html", "a\\b.html", ".env", "x.php", "x.map", "a/../b.js"):
            with self.subTest(name=name), self.assertRaises(AppError):
                promote(self.root, archive({"index.html": "ok", name: "no"}), entrypoint="index.html")
        self.assertFalse((self.root.parent / "outside.html").exists())

    def test_symlink_duplicate_and_bomb(self):
        for kind in ("link", "duplicate", "bomb"):
            with self.subTest(kind=kind):
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    z.writestr("index.html", "ok")
                    if kind == "link":
                        info = zipfile.ZipInfo("link.html")
                        info.create_system = 3
                        info.external_attr = 0o120777 << 16
                        z.writestr(info, "../private")
                    elif kind == "duplicate":
                        z.writestr("index.html", "other")
                    else:
                        z.writestr("huge.txt", "a" * 1_000_000)
                with self.assertRaises(AppError):
                    promote(self.root, buf.getvalue(), entrypoint="index.html")


class BindingTests(unittest.TestCase):
    def test_compare_and_swap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public_id = "a" * 32
            value = {"public_id": public_id, "hostname": f"site-{public_id}.apps.example.test",
                     "generation": 1, "enabled": False, "archived": False,
                     "current": None, "previous": None, "operation_id": "op_test"}
            write_binding(root, public_id, value, expected_generation=0)
            self.assertEqual(read_binding(root / "public", public_id)["generation"], 1)
            with self.assertRaises(AppError):
                write_binding(root, public_id, value, expected_generation=0)
            path = root / "public/bindings" / f"{public_id}.json"
            path.write_text("{")
            with self.assertRaises(AppError):
                read_binding(root / "public", public_id)

    def test_host_path_contract(self):
        self.assertEqual(canonical_host("Site.apps.example.test", "apps.example.test"), "site.apps.example.test")
        for value in ("foo.evil.test", "foo.apps.example.test:80", "a.apps.example.test,evil", "a.apps.example.test."):
            with self.assertRaises(AppError):
                canonical_host(value, "apps.example.test")
        for value in ("/%2e%2e/secret", "/a%2fb", "/%252e%252e", "/a\\b", "/a//b", "/a\tb", "/a#b", "/a\x7fb"):
            with self.assertRaises(AppError):
                canonical_path(value)


if __name__ == "__main__":
    unittest.main()
