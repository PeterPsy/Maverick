from __future__ import annotations

import unittest

from core.api.app_frame_assets import rewrite_public_app_asset_urls


class AppFrameAssetTests(unittest.TestCase):
    def test_public_asset_attributes_use_the_exact_platform_origin(self) -> None:
        html = (
            '<script src="/apps/storage/assets/app-one.js"></script>'
            "<link HREF = '/apps/storage/assets/app-one.css?theme=dark'>"
        )

        rewritten = rewrite_public_app_asset_urls(html, "https://maverick.test")

        self.assertIn('src="https://maverick.test/apps/storage/assets/app-one.js"', rewritten)
        self.assertIn("HREF = 'https://maverick.test/apps/storage/assets/app-one.css?theme=dark'", rewritten)

    def test_api_navigation_and_existing_absolute_urls_are_unchanged(self) -> None:
        html = (
            '<a href="/apps/storage/route">route</a>'
            '<script src="/apps/storage/backend"></script>'
            '<script src="https://cdn.example/apps/storage/assets/app.js"></script>'
        )

        self.assertEqual(rewrite_public_app_asset_urls(html, "https://maverick.test"), html)


if __name__ == "__main__":
    unittest.main()
