"""Product providers never inherit the external operator's development login."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from core.providers.source_homes import codex_source_home, antigravity_source_home


class SourceHomeTests(unittest.TestCase):
    def test_ambient_codex_home_cannot_supply_product_auth(self):
        root = Path(__file__).resolve().parents[3]
        with patch.dict(os.environ, {'CODEX_HOME': '/root/.codex', 'LOOPINO_CODEX_HOME': ''}):
            self.assertEqual(codex_source_home(), root / 'data/provider-auth/codex')
            self.assertEqual(antigravity_source_home(), root / 'data/provider-auth/antigravity')

    def test_explicit_product_home_is_respected(self):
        with patch.dict(os.environ, {'LOOPINO_CODEX_HOME': '/projects/loopino/data/provider-auth/test'}):
            self.assertEqual(codex_source_home(), Path('/projects/loopino/data/provider-auth/test'))
