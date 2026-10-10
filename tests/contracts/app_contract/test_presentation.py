"""App-owned sidebar presentation stays explicit and survives normalization."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.apps.contract_parser_metadata import parse_presentation_section
from core.apps.contracts import (
    app_contract_payload,
    build_app_contract,
    build_app_entrypoints,
    build_app_presentation,
    build_parsed_app_contract,
    parse_app_contract_file,
    write_app_contract_file,
)
from core.apps.errors import AppContractValidationError


class SidebarPresentationTests(unittest.TestCase):
    def test_sidebar_defaults_enabled_and_accepts_explicit_boolean(self) -> None:
        for value, expected in (({}, True), ({"sidebar_enabled": True}, True), ({"sidebar_enabled": False}, False)):
            with self.subTest(value=value):
                presentation = parse_presentation_section({"frontend_role": "workspace", **value}, has_frontend_entrypoint=True)
                self.assertEqual(presentation.sidebar_enabled, expected)

    def test_sidebar_rejects_non_boolean_modes(self) -> None:
        for value in (None, "false", 0, 1, [], {}):
            with self.subTest(value=value), self.assertRaises(AppContractValidationError):
                parse_presentation_section({"frontend_role": "workspace", "sidebar_enabled": value}, has_frontend_entrypoint=True)

    def test_disabled_sidebar_survives_contract_round_trip(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "frontend/dist").mkdir(parents=True)
            parsed = build_parsed_app_contract(
                app_id="canvas-app", name="Canvas", version="1.0.0", description="Canvas app", publisher="test",
                contract=build_app_contract(
                    presentation=build_app_presentation(frontend_role="workspace", sidebar_enabled=False),
                    entrypoints=build_app_entrypoints(frontend="frontend/dist"),
                ),
            )
            write_app_contract_file(root, parsed)
            loaded = parse_app_contract_file(root)
            self.assertFalse(loaded.contract.presentation.sidebar_enabled)
            self.assertEqual(app_contract_payload(loaded)["presentation"], {"frontend_role": "workspace", "sidebar_enabled": False})

    def test_only_design_studio_disables_sidebar_in_current_apps(self) -> None:
        root = Path(__file__).resolve().parents[3]
        disabled = []
        for contract in (root / "apps").glob("*/app_contract.json"):
            parsed = parse_app_contract_file(contract.parent)
            if not parsed.contract.presentation.sidebar_enabled:
                disabled.append(parsed.app_id)
        self.assertEqual(disabled, ["design-studio"])
