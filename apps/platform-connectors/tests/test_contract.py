"""Declared surfaces match the source catalog and executable entrypoints."""

from __future__ import annotations

from pathlib import Path
import json
from tempfile import TemporaryDirectory
import unittest

from core.apps.contracts import parse_app_contract_file
from core.shared.entrypoints import run_json_entrypoint


class ConnectorsContractTests(unittest.TestCase):
    def test_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        self.assertEqual(parsed.app_id, "platform-connectors")
        tools=json.loads((app_root/'mcp/tool_schemas.json').read_text())['tools']
        self.assertEqual(set(parsed.contract.capabilities.mcp_tools),set(tools))
        self.assertEqual(tools['connectors_run_refresh']['effect_class'],'mutating')
        self.assertEqual(tools['connectors_collection_delete']['effect_class'],'destructive')
        self.assertTrue(parsed.contract.presentation.sidebar_enabled)
        sidebar = json.loads((app_root / 'app_contract.json').read_text())['widgets'][0]
        self.assertEqual(sidebar['host'], 'base-shell')
        self.assertEqual(sidebar['content_kinds'], ['shell.sidebar.primary'])
        self.assertTrue((app_root / sidebar['frontend']['mount'] / 'index.html').is_file())

    def test_cli_mcp_and_backend_preserve_manifest_and_actor_boundaries(self):
        app=Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temporary:
            payload={'workspace_id':'fixture','app_id':'platform-connectors','data_root':temporary}
            for relative,request in [('cli/app_cli.py',{'arguments':{'action':'references.manifest'}}),
                                     ('mcp/server.py',{'tool_name':'platform_connectors_reference_manifest','arguments':{}})]:
                manifest=run_json_entrypoint(app/relative,payload=payload|request,cwd=app)
                self.assertEqual(manifest['app_id'],'platform-connectors')
                self.assertEqual(manifest['entity_types'][0]['entity_type'],'collection')
            denied=run_json_entrypoint(app/'backend/app_backend.py',payload=payload|{'body':{'action':'status'}},cwd=app)
            self.assertEqual(denied['status_code'],403)
            self.assertFalse((Path(temporary)/'connectors.sqlite3').exists())

    def test_sidebar_catalog_requires_actor_and_does_not_read_private_history(self):
        app = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temporary:
            payload = {'workspace_id':'fixture','app_id':'platform-connectors','data_root':temporary,
                       'body':{'action':'sources.list'}}
            denied = run_json_entrypoint(app/'backend/app_backend.py', payload=payload, cwd=app)
            self.assertEqual(denied['status_code'], 403)
            result = run_json_entrypoint(app/'backend/app_backend.py', payload=payload|{'user_id':'fixture-user'}, cwd=app)
            self.assertEqual(result['status_code'], 200)
            self.assertEqual(result['json']['sources'][0]['id'], 'instagram')
            self.assertEqual(len(result['json']['sources']), 9)
            self.assertEqual(set(result['json']), {'sources'})
            self.assertFalse((Path(temporary)/'connectors.sqlite3').exists())


if __name__ == "__main__":
    unittest.main()
