"""Browser font declarations must not grant scripts or API access."""

import unittest

from core.api.sidecar_browser import _content_security_policy


class SidecarFontCspTests(unittest.TestCase):
    def test_declared_font_hosts_are_limited_to_styles_and_fonts(self) -> None:
        policy = _content_security_policy(
            "https://maverick.example",
            parent_origin="https://af-app.sidecars.maverick.example",
            style_origins=["https://fonts.googleapis.com"],
            font_origins=["https://fonts.gstatic.com"],
        )
        directives = dict(d.split(" ", 1) for d in policy.split("; "))
        self.assertEqual(directives["style-src"], "'self' 'unsafe-inline' https://fonts.googleapis.com")
        self.assertEqual(directives["font-src"], "'self' data: https://fonts.gstatic.com")
        self.assertEqual(directives["script-src"], "'self' 'unsafe-inline'")
        self.assertEqual(directives["connect-src"], "'self'")
        self.assertEqual(directives["frame-ancestors"], "'self' https://maverick.example https://af-app.sidecars.maverick.example")

    def test_fonts_remain_same_origin_by_default(self) -> None:
        policy = _content_security_policy("https://maverick.example")
        self.assertIn("font-src 'self' data:;", policy)
        self.assertIn("style-src 'self' 'unsafe-inline';", policy)


if __name__ == "__main__":
    unittest.main()
