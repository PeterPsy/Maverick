"""Generated contract smoke test."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

for parent in Path(__file__).resolve().parents:
    if (parent / "core").is_dir():
        sys.path.insert(0, str(parent))
        break

from core.apps.contracts import parse_app_contract_file


class GeneratedAppContractTest(unittest.TestCase):
    def test_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        self.assertEqual(parsed.app_id, "crm")
        self.assertEqual([widget.widget_id for widget in parsed.contract.widgets], ["crm-sidebar"])


if __name__ == "__main__":
    unittest.main()
