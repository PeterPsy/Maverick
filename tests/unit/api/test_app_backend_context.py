"""App contracts, not untrusted request bodies, select optional backend context."""

import json
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.service import install_store_app, register_app_source_from_contract
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class BackendContextTests(AppReferenceApiTestSupport, unittest.TestCase):
    def test_workspace_catalog_is_backward_compatible_and_can_be_omitted_by_contract(self):
        for include in (None, False):
            with self.subTest(include=include), tempfile.TemporaryDirectory() as temporary:
                root = self._repo_root(temporary)
                app_root = root / 'apps/records'
                self._write_reference_app(app_root)
                (app_root / 'backend.py').write_text(
                    'import json, sys\np = json.load(sys.stdin)\n'
                    'print(json.dumps({"status_code": 200, "json": {"items": p["workspace_apps"]["items"], "user": p["user_id"]}}))\n')
                path = app_root / 'app_contract.json'
                contract = json.loads(path.read_text())
                contract['entrypoints']['backend'] = 'backend.py'
                if include is not None:
                    contract['capabilities']['backend_workspace_apps'] = include
                path.write_text(json.dumps(contract))
                with patch.dict('os.environ', {'MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS': '1',
                        'MAVERICK_ADMIN_USERNAME': 'admin', 'MAVERICK_ADMIN_PASSWORD': 'maverick'}):
                    state = bootstrap_platform_state(start_path=root)
                source = register_app_source_from_contract(state.app_store, source_kind='platform', source_path=str(app_root))
                install_store_app(state.app_store, source_id=source.source_id, workspace_id='default', start_path=root)
                host = PlatformHost(state, start_path=root)
                cookie = self._login(host)
                with patch('core.api.app_mounts.enabled_app_items', return_value=[{'app_id': 'visible'}]) as discovery:
                    status, payload, _ = self._invoke(host, path='/api/apps/records/backend', method='POST', cookie=cookie,
                        body={'backend_workspace_apps': include is False})
                self.assertEqual(status, 200)
                self.assertTrue(payload['user'])
                self.assertEqual(payload['items'], [] if include is False else [{'app_id': 'visible'}])
                self.assertEqual(discovery.call_count, 0 if include is False else 1)
