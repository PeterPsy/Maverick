"""Email rendering policy tests."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = APP_ROOT / "tests" / "fixtures"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))

from backend.email_rendering import render_email_body, sanitize_email_html, truncate_sanitized_html


class ParsedEmailHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.style_text: list[str] = []
        self._style_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self.tags.append((tag, {name.lower(): str(value or "") for name, value in attrs}))
        if tag == "style":
            self._style_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style" and self._style_depth:
            self._style_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._style_depth:
            self.style_text.append(data)

    def all(self, tag: str) -> list[dict[str, str]]:
        return [attrs for current, attrs in self.tags if current == tag]

    def first(self, tag: str, **attrs: str) -> dict[str, str] | None:
        expected = {
            ("class" if name == "class_" else name.replace("_", "-")): value
            for name, value in attrs.items()
        }
        for current, current_attrs in self.tags:
            if current != tag:
                continue
            if all(current_attrs.get(name) == value for name, value in expected.items()):
                return current_attrs
        return None


def fixture_html(name: str) -> str:
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


def parse_email_html(value: str) -> ParsedEmailHTML:
    parser = ParsedEmailHTML()
    parser.feed(value)
    parser.close()
    return parser


class EmailRenderingTest(unittest.TestCase):
    def test_render_email_body_sanitizes_html_and_builds_preview(self) -> None:
        html_body = """
        <style>
          @import url("https://tracker.example/import.css");
          @media only screen and (max-width: 600px) {
            .desktop { display: none !important; }
          }
          .hero { background-image: url("https://tracker.example/hero.png"); color: #fff; }
        </style>
        <div class="desktop hero" id="hero-card" onclick="steal()">
          <p style="color: #123456">Hello <strong>HTML</strong></p>
          <span style="background:u\\72l(https://tracker.example/style.png) #990000; color: red">Styled</span>
          <table background="https://tracker.example/background.png"><tr><td>Background</td></tr></table>
          <a href="https://example.com" onclick="steal()">Open</a>
          <img src="https://tracker.example/pixel.png" alt="tracker" width="1" height="1">
          <img src="cid:logo123" alt="logo">
          <script>steal()</script>
        </div>
        """

        rendered = render_email_body(["Hello HTML"], [html_body])

        self.assertEqual(rendered.body_text, "Hello HTML")
        self.assertEqual(rendered.body_preview, "Hello HTML")
        self.assertEqual(rendered.body_render_mode, "html")
        self.assertFalse(rendered.body_truncated)
        self.assertEqual(rendered.body_html_sanitized, rendered.body_html_rendered)
        self.assertIn("<script>steal()</script>", rendered.body_html_original_bounded)
        self.assertIn("<style>", rendered.body_html_gmail_sanitized)
        self.assertEqual(rendered.render_policy["version"], 2)
        self.assertEqual(rendered.render_policy["rendered_from"], "body_html_gmail_sanitized")
        self.assertIn("<style>", rendered.body_html_sanitized)
        self.assertIn("@media only screen", rendered.body_html_sanitized)
        self.assertIn('class="desktop hero"', rendered.body_html_sanitized)
        self.assertIn('id="hero-card"', rendered.body_html_sanitized)
        self.assertIn("<strong>HTML</strong>", rendered.body_html_sanitized)
        self.assertIn('style="color: #123456"', rendered.body_html_sanitized)
        self.assertIn('style="background: #990000; color: red"', rendered.body_html_sanitized)
        self.assertIn('href="https://example.com"', rendered.body_html_sanitized)
        self.assertIn('target="_blank"', rendered.body_html_sanitized)
        self.assertIn("mail-blocked-image", rendered.body_html_sanitized)
        self.assertIn('data-mail-background-image="https://tracker.example/style.png"', rendered.body_html_sanitized)
        self.assertIn('data-mail-background-image="https://tracker.example/background.png"', rendered.body_html_sanitized)
        self.assertNotIn("onclick", rendered.body_html_sanitized)
        self.assertNotIn("<script", rendered.body_html_sanitized)
        self.assertNotIn("src=", rendered.body_html_sanitized)
        self.assertNotIn("@import", rendered.body_html_sanitized)
        self.assertNotIn("url(", rendered.body_html_sanitized)
        self.assertNotIn("u\\72l", rendered.body_html_sanitized)
        self.assertNotIn("hero.png", rendered.body_html_sanitized)

    def test_render_email_body_falls_back_to_html_text(self) -> None:
        rendered = render_email_body([], ["<div>Hello<br><strong>fallback</strong></div>"])

        self.assertEqual(rendered.body_text, "Hello\n fallback")
        self.assertEqual(rendered.body_preview, "Hello fallback")
        self.assertEqual(rendered.body_render_mode, "html")

    def test_render_email_body_fallback_text_ignores_style_blocks(self) -> None:
        rendered = render_email_body(
            [],
            [
                """
                <style>
                  .hidden { display: none; }
                  @media only screen and (max-width: 600px) { .stack { display: block; } }
                </style>
                <div>Visible <strong>fallback</strong></div>
                """,
            ],
        )

        self.assertEqual(rendered.body_text, "Visible fallback")
        self.assertEqual(rendered.body_preview, "Visible fallback")
        self.assertNotIn("hidden", rendered.body_text)
        self.assertNotIn("@media", rendered.body_preview)

    def test_render_email_body_tracks_combined_source_truncation(self) -> None:
        rendered = render_email_body(["a" * 8, "b" * 8], ["<p>ok</p>"], source_limit=12)

        self.assertEqual(rendered.body_text, "aaaaaaaa\n\nbb")
        self.assertTrue(rendered.body_truncated)

    def test_truncate_sanitized_html_closes_open_tags(self) -> None:
        body_html = "<div><p>" + ("Long body " * 80) + "</p></div>"

        truncated = truncate_sanitized_html(body_html, 220)

        self.assertTrue(truncated.endswith("</p></div>"))
        self.assertNotIn("<p", truncated[-10:])

    def test_sanitize_email_html_skips_unsafe_containers(self) -> None:
        sanitized = sanitize_email_html("<form><button>Bad</button></form><p>Good</p>")

        self.assertEqual(sanitized, "<p>Good</p>")

    def test_sanitize_email_html_strips_forged_mail_data_metadata(self) -> None:
        sanitized = sanitize_email_html(
            """
            <span class="mail-blocked-image"
                  data-mail-image="https://attacker.example/tracker.png"
                  data-mail-alt="forged alt"
                  data-mail-width="1200"
                  data-mail-style="width:1200px">
              forged placeholder
            </span>
            <div data-mail-background-image="https://attacker.example/background.png"
                 data-smartmail="gmail_signature"
                 data-custom="kept"
                 style="background-image: url(https://images.example.com/real-bg.png); color: blue">
              background
            </div>
            <img src="https://images.example.com/real.png"
                 data-mail-image="https://attacker.example/fake-real.png"
                 alt="real image"
                 width="24"
                 height="16">
            """
        )
        dom = parse_email_html(sanitized)

        forged_placeholder = dom.first("span", class_="mail-blocked-image")
        self.assertIsNotNone(forged_placeholder)
        self.assertNotIn("data-mail-image", forged_placeholder)
        self.assertNotIn("data-mail-style", forged_placeholder)
        self.assertIsNone(dom.first("div", **{"data-mail-background-image": "https://attacker.example/background.png"}))
        signature = dom.first("div", **{"data-smartmail": "gmail_signature"})
        self.assertIsNotNone(signature)
        self.assertEqual(signature["data-custom"], "kept")
        self.assertEqual(signature["data-mail-background-image"], "https://images.example.com/real-bg.png")

        generated_placeholders = [
            attrs for attrs in dom.all("span")
            if attrs.get("class") == "mail-blocked-image" and attrs.get("data-mail-image")
        ]
        self.assertEqual([attrs["data-mail-image"] for attrs in generated_placeholders], ["https://images.example.com/real.png"])
        self.assertEqual(generated_placeholders[0]["data-mail-width"], "24")
        self.assertEqual(generated_placeholders[0]["data-mail-height"], "16")
        self.assertNotIn("attacker.example", sanitized)

    def test_sanitize_email_html_keeps_gmail_supported_css_properties(self) -> None:
        sanitized = sanitize_email_html(
            """
            <style>
              @media only screen and (min-width: 500px) and (orientation: landscape) {
                #hero.hero { table-layout: fixed; border-collapse: collapse; position: absolute; color: red; }
              }
              @media print { .print { color: red; } }
              @supports (display: grid) { .grid { color: red; } }
              .hero { direction: rtl; float: right; text-indent: 12px; word-spacing: 2px; transform: scale(2); }
              .asset { background-size: cover; background-image: url("https://tracker.example/bg.png"); }
            </style>
            <table style="border-collapse: collapse; table-layout: fixed; direction: rtl; background-image: url(https://tracker.example/inline.png); color: green; behavior: url(#bad); position: absolute; transform: scale(2)">
              <tr><td style="list-style-type: square; text-indent: 8px; word-spacing: 1px; zoom: 1">Cell</td></tr>
            </table>
            """
        )

        self.assertIn("@media only screen and (min-width: 500px) and (orientation: landscape)", sanitized)
        self.assertIn("table-layout: fixed", sanitized)
        self.assertIn("border-collapse: collapse", sanitized)
        self.assertIn("direction: rtl", sanitized)
        self.assertIn("float: right", sanitized)
        self.assertIn("text-indent: 12px", sanitized)
        self.assertIn("word-spacing: 2px", sanitized)
        self.assertIn("background-size: cover", sanitized)
        self.assertIn('style="border-collapse: collapse; table-layout: fixed; direction: rtl; color: green"', sanitized)
        self.assertIn('style="list-style-type: square; text-indent: 8px; word-spacing: 1px; zoom: 1"', sanitized)
        self.assertNotIn("@media print", sanitized)
        self.assertNotIn("@supports", sanitized)
        self.assertNotIn("position:", sanitized)
        self.assertNotIn("transform:", sanitized)
        self.assertNotIn("behavior:", sanitized)
        self.assertNotIn("url(", sanitized)
        self.assertNotIn("bg.png", sanitized)

    def test_newsletter_fixture_preserves_table_layout_and_responsive_css(self) -> None:
        rendered = render_email_body(["Hello HTML"], [fixture_html("newsletter_table_responsive.html")])
        sanitized = rendered.body_html_rendered
        dom = parse_email_html(sanitized)
        style_text = " ".join(dom.style_text)

        self.assertEqual(rendered.body_render_mode, "html")
        self.assertFalse(rendered.body_truncated)
        self.assertIsNotNone(dom.first("table", role="presentation", width="640", cellpadding="0", cellspacing="0"))
        self.assertIsNotNone(dom.first("td", id="hero-card"))
        self.assertGreaterEqual(len(dom.all("tr")), 2)
        self.assertGreaterEqual(len(dom.all("td")), 3)
        self.assertIn("@media only screen and (max-width: 600px)", style_text)
        self.assertIn(".container { width: 100% !important }", style_text)
        self.assertIn(".stack { display: block !important; width: 100% !important }", style_text)
        self.assertIn(".preheader { display: none; max-height: 0; overflow: hidden }", style_text)

        blocked_images = [
            attrs for attrs in dom.all("span")
            if attrs.get("class") == "mail-blocked-image"
        ]
        self.assertEqual(
            [attrs["data-mail-image"] for attrs in blocked_images],
            ["https://tracker.example/pixel.png", "cid:logo123"],
        )
        self.assertEqual(blocked_images[0]["data-mail-width"], "1")
        self.assertEqual(blocked_images[0]["data-mail-height"], "1")
        self.assertEqual(blocked_images[1]["data-mail-width"], "96")
        self.assertEqual(blocked_images[1]["data-mail-height"], "32")
        hero_cell = dom.first("td", id="hero-card")
        self.assertIsNotNone(hero_cell)
        self.assertEqual(hero_cell["data-mail-background-image"], "https://tracker.example/background.png")
        self.assertIn("background: #990000", hero_cell["style"])
        self.assertNotIn("src=", sanitized)
        self.assertNotIn("<script", sanitized)
        self.assertNotIn("@import", sanitized)
        self.assertNotIn("url(", sanitized)

    def test_gmail_signature_and_quote_fixture_keep_reader_structure(self) -> None:
        sanitized = sanitize_email_html(fixture_html("gmail_signature_quote.html"))
        dom = parse_email_html(sanitized)

        signature = dom.first("div", class_="gmail_signature")
        quote = dom.first("blockquote", class_="gmail_quote")
        mail_link = dom.first("a", href="mailto:alex@example.com")
        context_link = dom.first("a", href="https://example.com/context")

        self.assertIsNotNone(signature)
        self.assertEqual(signature["data-smartmail"], "gmail_signature")
        self.assertIsNotNone(quote)
        self.assertIn("border-left: 1px solid #cccccc", quote["style"])
        self.assertIn("padding-left: 1ex", quote["style"])
        self.assertIsNotNone(mail_link)
        self.assertEqual(mail_link["target"], "_blank")
        self.assertIsNotNone(context_link)
        self.assertEqual(context_link["rel"], "noopener noreferrer")

        blocked_images = [
            attrs for attrs in dom.all("span")
            if attrs.get("class") == "mail-blocked-image"
        ]
        self.assertEqual(
            [attrs["data-mail-image"] for attrs in blocked_images],
            ["cid:ii_signature_logo", "https://images.example.com/quoted-banner.png"],
        )
        self.assertEqual(blocked_images[0]["data-mail-alt"], "Company logo")
        self.assertEqual(blocked_images[1]["data-mail-width"], "320")
        self.assertNotIn("src=", sanitized)

    def test_security_fixture_keeps_safe_dom_and_removes_active_content(self) -> None:
        sanitized = sanitize_email_html(fixture_html("security_edge_cases.html"))
        dom = parse_email_html(sanitized)

        self.assertIsNone(dom.first("form"))
        self.assertIsNone(dom.first("iframe"))
        self.assertIsNone(dom.first("button"))
        self.assertIsNone(dom.first("a", href="javascript:alert(1)"))
        self.assertIsNotNone(dom.first("a", href="https://example.com/safe"))
        paragraph = dom.first("p")
        self.assertIsNotNone(paragraph)
        self.assertEqual(paragraph["style"], "color: green")
        self.assertIn("Safe text", sanitized)
        self.assertIn("mail-blocked-image", sanitized)
        self.assertNotIn("onclick", sanitized)
        self.assertNotIn("onerror", sanitized)
        self.assertNotIn("position:", sanitized)
        self.assertNotIn("javascript:", sanitized)


if __name__ == "__main__":
    unittest.main()
