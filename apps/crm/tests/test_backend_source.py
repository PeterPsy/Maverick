"""Backend entrypoint source smoke checks."""

from __future__ import annotations

from pathlib import Path
import unittest


BACKEND_ENTRYPOINT = Path(__file__).resolve().parents[1] / "backend" / "app_backend.py"


class CrmBackendSourceTest(unittest.TestCase):
    def test_backend_mount_returns_structured_unexpected_errors(self) -> None:
        source = BACKEND_ENTRYPOINT.read_text(encoding="utf-8")

        self.assertIn("except Exception as error", source)
        self.assertIn('"error": "internal_error"', source)
        self.assertIn('"message": "Unexpected CRM backend error."', source)


if __name__ == "__main__":
    unittest.main()
