from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from core.apps.frontend_assets import (
    FRONTEND_ASSET_MANIFEST_NAME,
    FrontendAssetManifestError,
    load_frontend_asset_manifest,
    write_conservative_frontend_asset_manifest,
)


class FrontendAssetsTestCase(unittest.TestCase):
    def test_conservative_manifest_verifies_files_without_claiming_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("<main>Maverick</main>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app-semantic-name.js").write_text("export {};", encoding="utf-8")

            generated = write_conservative_frontend_asset_manifest(root)
            loaded = load_frontend_asset_manifest(root, required=True, verify_files=True)

        self.assertEqual(generated, loaded)
        self.assertEqual(generated.immutable, ())
        self.assertIn("assets/app-semantic-name.js", {record.path for record in generated.revalidated})

    def test_manifest_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("ok", encoding="utf-8")
            _write_manifest(root, immutable=[_record("../escape.js", b"bad")])

            with self.assertRaisesRegex(FrontendAssetManifestError, "Unsafe frontend asset path"):
                load_frontend_asset_manifest(root, required=True, verify_files=True)

    def test_manifest_rejects_wrong_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_bytes(b"actual")
            record = _record("index.html", b"bogus!")
            _write_manifest(root, entrypoints=["index.html"], revalidated=[record])

            with self.assertRaisesRegex(FrontendAssetManifestError, "Digest mismatch"):
                load_frontend_asset_manifest(root, required=True, verify_files=True)

    def test_manifest_rejects_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_bytes(b"ok")
            _write_manifest(root, immutable=[_record("assets/missing.js", b"missing")])

            with self.assertRaisesRegex(FrontendAssetManifestError, "Missing declared frontend asset"):
                load_frontend_asset_manifest(root, required=True, verify_files=True)


def _record(path: str, body: bytes) -> dict[str, object]:
    return {"path": path, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


def _write_manifest(
    root: Path,
    *,
    entrypoints: list[str] | None = None,
    immutable: list[dict[str, object]] | None = None,
    revalidated: list[dict[str, object]] | None = None,
) -> None:
    payload = {
        "schema": "maverick.frontend-assets.v1",
        "build_id": "a" * 64,
        "entrypoints": entrypoints or ["index.html"],
        "immutable": immutable or [],
        "revalidated": revalidated or [_record("index.html", b"ok")],
    }
    (root / FRONTEND_ASSET_MANIFEST_NAME).write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
