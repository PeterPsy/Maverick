from __future__ import annotations

import unittest

from core.api.app_mounts import is_public_app_static_asset


class AppStaticAssetPolicyTest(unittest.TestCase):
    def test_app_owned_compact_icon_is_public(self) -> None:
        self.assertTrue(is_public_app_static_asset("maverick-icon-compact.png"))

    def test_compact_icon_allowlist_does_not_expose_similar_paths(self) -> None:
        for path in (
            "other-icon.png",
            "private/maverick-icon-compact.png",
            "maverick-icon-compact.png/private.json",
        ):
            with self.subTest(path=path):
                self.assertFalse(is_public_app_static_asset(path))

    def test_vite_worker_media_and_wasm_outputs_are_public(self) -> None:
        for path in (
            "assets/pdf.worker-contenthash.mjs",
            "assets/count-down-contenthash.mp3",
            "assets/decoder-contenthash.wasm",
        ):
            with self.subTest(path=path):
                self.assertTrue(is_public_app_static_asset(path))


if __name__ == "__main__":
    unittest.main()
