"""The public product catalog uses official SDK packages and selected sources."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.app_sdk.models import AppSdkCreateRequest
from core.app_sdk.service import create_app_source
from core.apps.remote_store import fetch_remote_catalog, resolve_remote_app_version, _extract_bundle
from scripts.export_product_catalog import export_catalog


class ProductCatalogTests(unittest.TestCase):
    def test_selected_sdk_artifact_resolves_and_excludes_runtime_and_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'core').mkdir()
            (root / 'apps').mkdir()
            (root / 'AGENTS.md').touch()
            for name in ('standard', 'company-extension'):
                create_app_source(AppSdkCreateRequest(app_id=name, template_id='minimal', target_kind='platform'), start_path=root)
            app = root / 'apps/standard'
            (app / 'runtime').mkdir()
            (app / 'runtime/private.json').write_text('excluded')
            (app / '.env').write_text('excluded')
            (app / 'credential.key').write_text('excluded')
            (root / 'apps/bootstrap.json').write_text(json.dumps({'schema_version':'1','app_ids':['standard']}))
            output = root / 'installation/catalog'
            catalog = export_catalog(root, output)
            self.assertEqual(catalog['count'], 1)
            self.assertEqual(catalog['items'][0]['app_id'], 'standard')
            version = catalog['items'][0]['versions'][0]
            self.assertEqual(version['status'], 'published')
            self.assertTrue(version['artifact_download_url'].startswith('https://loopino.giuntitrail.com/catalog/artifacts/'))
            artifact = output / 'artifacts' / version['artifact_download_url'].rsplit('/',1)[1]
            self.assertIn(version['sha256'], artifact.name)
            self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(),version['sha256'])
            manifest = json.loads(Path(str(artifact)+'.manifest.json').read_text())
            self.assertEqual(manifest['provenance']['packager'],'loopino-app-sdk')
            self.assertTrue(set(manifest['files']).isdisjoint({'.env','credential.key','runtime/private.json'}))
            with patch('core.apps.remote_store._read_url_json',return_value=catalog) as read:
                self.assertEqual(fetch_remote_catalog()['count'],1)
                resolved = resolve_remote_app_version('https://loopino.giuntitrail.com/catalog',app_id='standard')
                self.assertEqual(resolved.sha256,version['sha256'])
                read.assert_called_with('https://loopino.giuntitrail.com/catalog/api/apps')
            extracted = _extract_bundle(artifact, root / 'extracted')
            self.assertTrue((extracted / 'app_contract.json').is_file())
            for target in (root, root / 'apps/catalog', root.parent / 'external-catalog'):
                with self.subTest(target=target), self.assertRaises(ValueError):
                    export_catalog(root, target)

    def test_unsafe_origin_and_symlink_output_are_denied(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'installation').symlink_to(root.parent, target_is_directory=True)
            with self.assertRaises(ValueError):
                export_catalog(root, root / 'installation/catalog')
