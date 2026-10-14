"""Installation selection separates distributed source from first-boot enablement."""

import json
from pathlib import Path
import tempfile
import unittest

from core.apps.builtin_apps import discover_builtin_apps
from core.apps.errors import AppContractValidationError


class BootstrapSelectionTests(unittest.TestCase):
    def test_only_selected_sources_are_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'AGENTS.md').touch()
            (root / 'core').mkdir()
            for name in ('standard', 'private-extension'):
                app = root / 'apps' / name
                app.mkdir(parents=True)
                (app / 'app_contract.json').write_text('{}')
            selection = root / 'apps/bootstrap.json'
            selection.write_text(json.dumps({'schema_version': '1', 'app_ids': ['standard']}))
            self.assertEqual([spec.app_id for spec in discover_builtin_apps(start_path=root)], ['standard'])
            for ids in (['missing'], ['standard', 'standard'], [False]):
                selection.write_text(json.dumps({'schema_version': '1', 'app_ids': ids}))
                with self.subTest(ids=ids), self.assertRaises(AppContractValidationError):
                    discover_builtin_apps(start_path=root)

    def test_distribution_selection_is_standard_only(self):
        root = Path(__file__).resolve().parents[3]
        selected = {spec.app_id for spec in discover_builtin_apps(start_path=root)}
        self.assertTrue({'base-shell', 'chat', 'storage', 'skills', 'vault'} <= selected)
        self.assertTrue(selected.isdisjoint({'marta-ops', 'github-actions'}))
