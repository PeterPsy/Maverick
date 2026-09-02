from __future__ import annotations

import unittest

from core.api.app_mounts import is_public_app_static_asset


class AppStaticAssetPolicyTest(unittest.TestCase):
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
