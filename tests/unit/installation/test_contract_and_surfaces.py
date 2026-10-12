"""Endpoint ownership and admin policies are shared across installation clients."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.installation_api import handle_installation_api
from core.api.session_api import RequestSession
from core.apps.contract_builders import build_app_contract, build_parsed_app_contract
from core.apps.contract_installation import parse_installation
from core.apps.contract_parser_impl import parse_app_contract_file
from core.apps.contract_serializer import write_app_contract_file
from core.apps.errors import AppContractValidationError
from core.cli.installation_commands import installation_command_specs
from core.installation.errors import InstallationError
from core.installation.operations import invoke, OPERATIONS
from core.mcp.installation_tools import installation_tool_specs
from core.runtime.tool_schema import provider_safe_tool_schema


class ContractAndSurfacesTests(unittest.TestCase):
    def test_public_endpoint_roundtrip_and_ownership(self):
        entry = {'id': 'callback', 'kind': 'oauth_redirect', 'path': '/api/apps/{app_id}/oauth/callback', 'label': 'Demo'}
        declaration = parse_installation({'public_endpoints': [entry]}, 'demo')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_app_contract_file(root, build_parsed_app_contract(app_id='demo', name='Demo', version='1.0.0',
                description='Demo', publisher='maverick', contract=build_app_contract(installation=declaration)))
            self.assertEqual(parse_app_contract_file(root).contract.installation, declaration)
        for path in ['/api/apps/other/callback', '/api/apps/{app_id}/%2e%2e/secrets', '/api/apps/{app_id}/%5csecrets']:
            with self.subTest(path=path), self.assertRaises(AppContractValidationError):
                parse_installation({'public_endpoints': [{**entry, 'path': path}]}, 'demo')

    def test_catalog_schemas_are_provider_supported_and_types_checked(self):
        for _, specification, _ in OPERATIONS.values():
            provider_safe_tool_schema(specification)
        for arguments in [{'job_id': 4}, {'job_id': 'x' * 32, 'action_ids': 'all'}, {'job_id': 'x' * 32, 'action_ids': [True]}]:
            with self.assertRaises(InstallationError):
                invoke(None, 'confirm', arguments)

    def test_cli_requires_admin_and_mcp_denies_member(self):
        with tempfile.TemporaryDirectory() as folder:
            specs = installation_command_specs(start_path=Path(folder))
            self.assertEqual(len(specs), len(OPERATIONS))
            self.assertTrue(all(definition.invocation_policy.required_platform_role == 'admin' for definition, _ in specs))
            handler = installation_tool_specs(start_path=Path(folder))[0][1]
            with self.assertRaisesRegex(InstallationError, 'admin_required'):
                handler({}, SimpleNamespace(platform_role='member', caller_kind='agent'))

    def test_http_denies_non_admin_before_instantiating_service(self):
        context = RequestSession(SimpleNamespace(platform_role='member'), None, 'default')
        responses = []
        with patch('core.api.installation_api.require_session', return_value=context), patch('core.api.installation_api.service_for_state') as factory:
            result = handle_installation_api(None, {'PATH_INFO': '/api/admin/installation', 'REQUEST_METHOD': 'GET'}, lambda status, headers: responses.append(status))
        self.assertEqual(responses, ['403 Forbidden'])
        factory.assert_not_called()
        self.assertIn(b'admin_required', b''.join(result))
