"""Conserved source and rebuilt graphic bytes retain their explicit provenance."""

import hashlib
import json
from pathlib import Path
import unittest


class ProductGraphicContracts(unittest.TestCase):
    def test_original_graphics_have_existing_canonical_paths_and_unchanged_bytes(self):
        root = Path(__file__).resolve().parents[3]
        entries = json.loads((root / "docs/development/loopino_graphics_sha256.json").read_text())
        self.assertEqual(len(entries), 45)
        for entry in entries:
            with self.subTest(path=entry["after"]):
                path = root / entry["after"]
                self.assertTrue(path.is_relative_to(root))
                self.assertNotIn("maverick", entry["after"].lower())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])
