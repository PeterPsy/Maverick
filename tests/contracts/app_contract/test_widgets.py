"""Split tests from tests.support.cases.app_contract_cases.AppContractTestCase."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.apps.contract_widgets import parse_widget_declarations
from core.apps.contracts import build_app_entrypoints
from core.apps.errors import AppContractValidationError
from core.apps.widgets import widget_registry_item, widget_supports_host
from tests.support.cases import app_contract_cases as cases


_SELECTED = {
    'test_parse_contract_round_trips_widget_declarations',
    'test_parse_contract_rejects_duplicate_widget_ids',
    'test_parse_contract_rejects_unsafe_widget_mount',
    'test_parse_contract_rejects_widget_actions_without_surface',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.AppContractTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class AppContractWidgetTest(cases.AppContractTestCase):
    """Run the AppContractWidgetTest subset."""

    pass


_mask_unselected(AppContractWidgetTest)


class UniversalWidgetContractTests(unittest.TestCase):
    def test_universal_widget_parses_and_registry_binds_a_concrete_host(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "frontend").mkdir()
            declaration = {"widget_id": "preview", "host": "*", "content_kinds": ["file.preview"],
                "frontend": {"kind": "iframe", "mount": "frontend"}}
            widget = parse_widget_declarations(root, {"widgets": [declaration]}, build_app_entrypoints())[0]
            self.assertEqual(widget.host, "*")
            self.assertEqual(widget_registry_item("files", widget).host, "*")
            for host in ("chat", "mail"):
                self.assertTrue(widget_supports_host(widget.host, host))
                self.assertEqual(widget_registry_item("files", widget, host=host).host, host)
            self.assertFalse(widget_supports_host("*", "*"))
            self.assertFalse(widget_supports_host("*", ""))
            self.assertFalse(widget_supports_host("chat", "mail"))
            for host in ("**", "bad host", ""):
                with self.subTest(host=host), self.assertRaises(AppContractValidationError):
                    parse_widget_declarations(root, {"widgets": [{**declaration, "host": host}]}, build_app_entrypoints())
