"""Reusable entrypoints require an explicit, validated app contract declaration."""

from pathlib import Path
import tempfile
import unittest

from core.apps.contract_parser_entrypoints import parse_entrypoints_section
from core.apps.errors import AppContractValidationError


class JsonWorkerContractTests(unittest.TestCase):
    def test_worker_is_optional_and_requires_existing_backend_or_mcp(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "worker.py").write_text("pass\n")
            (root / "backend.py").write_text("pass\n")
            self.assertIsNone(parse_entrypoints_section(root, {}).json_worker)
            entrypoints = parse_entrypoints_section(root, {"backend": "backend.py", "json_worker": "worker.py"})
            self.assertEqual(entrypoints.json_worker, "worker.py")
            for payload in ({"json_worker": "worker.py"}, {"backend": "backend.py", "json_worker": "missing.py"},
                            {"backend": "backend.py", "json_worker": "../worker.py"},
                            {"backend": "backend.py", "json_worker": True}):
                with self.subTest(payload=payload), self.assertRaises(AppContractValidationError):
                    parse_entrypoints_section(root, payload)
