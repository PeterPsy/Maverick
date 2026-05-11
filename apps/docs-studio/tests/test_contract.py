"""Generated contract smoke test."""

from __future__ import annotations

from pathlib import Path
import unittest

from core.apps.contracts import parse_app_contract_file


class GeneratedAppContractTest(unittest.TestCase):
    def test_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        self.assertEqual(parsed.app_id, "docs-studio")

    def test_sidebar_widget_contract(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        widgets = {widget.widget_id: widget for widget in parsed.contract.widgets}

        self.assertIn("docs-studio-sidebar", widgets)
        widget = widgets["docs-studio-sidebar"]
        self.assertEqual(widget.host, "base-shell")
        self.assertEqual(widget.content_kinds, ["shell.sidebar.primary"])
        self.assertEqual(widget.frontend.mount, "frontend/dist/widgets/docs-studio-sidebar")
        self.assertTrue((app_root / widget.frontend.mount / "index.html").is_file())

    def test_frontend_removes_internal_assistant_and_header(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        frontend_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (app_root / "frontend" / "src").rglob("*")
            if path.is_file() and path.suffix in {".css", ".ts", ".tsx"}
        )

        obsolete_texts = (
            "Docs " + "Assistant",
            "AI " + "Ask",
            "Pub" + "lish",
            "Core " + "Docs",
            "Help " + "Center",
            "Change" + "log",
        )
        for obsolete_text in obsolete_texts:
            self.assertNotIn(obsolete_text, frontend_source)

        self.assertIn("maverick.widget.open-app", frontend_source)
        self.assertIn("maverick.app.selection-changed", frontend_source)


if __name__ == "__main__":
    unittest.main()
