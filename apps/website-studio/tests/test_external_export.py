"""Real Website Studio source/build -> bounded official external bundle."""
import base64
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from external_export import export_static_bundle
from external_export_assets import ExportError, prepare_assets
from store import create_site, read_file, validate_build, write_file


class ExternalExportTest(unittest.TestCase):
    def test_real_static_build_export_pins_assets_and_rejects_stale_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = create_site(root, display_name="Synthetic external export", slug="synthetic")
            original = read_file(root, site_id=site["id"], path="index.html")
            write_file(root, site_id=site["id"], path="index.html", content='<!doctype html><html><head><title>Demo</title></head><body><script src="/main.js"></script></body></html>', expected_hash=original["hash"])
            write_file(root, site_id=site["id"], path="main.js", content='document.body.dataset.demo="synthetic";', expected_hash="new")
            build = validate_build(root, site["id"])
            request = {"schema_version": "external-static-export-request.v1", "entity_type": "site",
                       "entity_id": site["id"], "build_id": build["id"], "release_id": "rel_" + "a" * 32,
                       "requested_format": "static_bundle"}
            exported = export_static_bundle(root, request)
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(exported["artifact"]["content_base64"]))) as archive:
                self.assertTrue({"index.html", "main.js"}.issubset(archive.namelist()))
                self.assertIn(b'/_releases/rel_', archive.read("index.html"))
            self.assertEqual(exported, export_static_bundle(root, request))
            write_file(root, site_id=site["id"], path="main.js", content="console.log('changed')", expected_hash=hashlib.sha256(b'document.body.dataset.demo="synthetic";').hexdigest())
            with self.assertRaisesRegex(ExportError, "build_stale"):
                export_static_bundle(root, request)

    def test_rebase_spa_built_chunks(self):
        files = {"index.html": b'<html><head></head><body><script type="module" src="/assets/main.js"></script></body></html>',
                 "assets/main.js": b'const chunk=()=>import("./chunk.js");const icon="/icon.svg";',
                 "assets/chunk.js": b'export default "synthetic";', "icon.svg": b'<svg></svg>'}
        result = prepare_assets(files, "rel_" + "b" * 32)
        self.assertIn(b'/_releases/rel_', result["index.html"])
        self.assertIn(b'/_releases/rel_', result["assets/main.js"])
        self.assertIn(b'import("./chunk.js")', result["assets/main.js"])

    def test_private_runtime_reference_is_not_exportable(self):
        with self.assertRaises(ExportError):
            prepare_assets({"index.html": b'<img src="/api/apps/storage/backend/media">'}, "rel_" + "a" * 32)


if __name__ == "__main__":
    unittest.main()
