"""Real CRM service behind a separately bounded anonymous HTTP adapter."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / 'backend'))

from errors import CrmError
from external_hosting import atomic_json, configure, hostname, status
from public_server.confinement import command
from public_server.policy import execute, PublicDenied
from public_server.server import Runtime
from service import handle_action


class PublicSurfaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'data'
        handle_action(self.root, 'crm.create_contact', {'display_name': 'Public contact', 'email': 'public@example.test'})
        atomic_json(self.root / 'external-hosting/deployment.json', {'installation_domain': 'maverick.example.test'})
        self.access = {'enabled': True, 'access': 'read-only', 'revision': 1}
        atomic_json(self.root / 'external-hosting/access.json', self.access)
        self.assets = self.base / 'assets'
        (self.assets / 'assets').mkdir(parents=True)
        (self.assets / 'index.html').write_text('<html lang="en"><script src="/apps/crm/assets/app.js"></script></html>')
        (self.assets / 'assets/app.js').write_text('test')
        self.projection = self.base / 'state/authority.json'
        atomic_json(self.projection, {'hostname': 'crm.apps.maverick.example.test', 'revision': 1, 'expires': time.time() + 8})
        self.runtime = Runtime(self.root, self.assets, self.projection, 'crm.apps.maverick.example.test', 'read-only')

    def request(self, path='/', method='GET', body=None, host='crm.apps.maverick.example.test', headers=None):
        return self.runtime.response(method, host, path, headers if headers is not None else {
            'origin': 'https://crm.apps.maverick.example.test', 'content-type': 'application/json',
        }, json.dumps(body).encode() if body is not None else b'')

    def test_native_reads_and_explicit_write_mode(self):
        code, result = execute(self.root, {'action': 'bootstrap'}, access='read-only')
        self.assertEqual(code, 200)
        self.assertEqual(result['contacts'][0]['display_name'], 'Public contact')
        self.assertEqual(result['view_state'], {})
        self.assertEqual(execute(self.root, {'action': 'crm.records_table', 'entity_type': 'contact'}, access='read-only')[0], 200)
        for action in ('crm.create_contact', 'delete_record', 'crm.import_apply'):
            with self.assertRaises(PublicDenied):
                execute(self.root, {'action': action}, access='read-only')
        code, result = execute(self.root, {'action': 'crm.create_account', 'name': 'Public write'}, access='read-write')
        self.assertEqual(code, 201)
        self.assertEqual(handle_action(self.root, 'crm.get_record', {'entity_type': 'account', 'id': result['account']['id']})[1]['record']['name'], 'Public write')

    def test_private_actions_and_forged_envelopes_never_dispatch(self):
        for action in ('crm.external.configure', 'crm.integration_callback', 'crm.integration_run',
                       'crm.integration_prepare', 'crm.integration_tick', 'crm.website_intake', 'health', 'future_action'):
            with self.subTest(action=action), self.assertRaises(PublicDenied):
                execute(self.root, {'action': action}, access='read-write')
        for key in ('_trusted_surface', '_app_dependencies', '_workspace_id', '_app_secret_request'):
            with self.subTest(key=key), self.assertRaises(PublicDenied):
                execute(self.root, {'action': 'bootstrap', key: 'forged'}, access='read-write')
        for action in ('crm.import_plan', 'crm.import_apply'):
            with self.assertRaises(PublicDenied):
                execute(self.root, {'action': action, 'source': {'format': 'crm_export', 'export': {}}}, access='read-write')

    def test_provider_workflow_cannot_be_approved_indirectly(self):
        from store import connect
        from domains.workflow import _create_workflow_proposal, _workflow_proposal
        contact = handle_action(self.root, 'bootstrap', {})[1]['contacts'][0]['id']
        with connect(self.root) as db:
            proposal = _create_workflow_proposal(db, 'integration', 'contact', contact, 'Private provider',
                {'action': {'type': 'provider_operation', 'operation_id': 'private-op'}}, source='test')
        for action in ('approve', 'apply', 'dismiss', 'reject'):
            with self.assertRaises(PublicDenied):
                execute(self.root, {'action': f'crm.{action}_workflow_proposal', 'id': proposal['id']}, access='read-write')
        with connect(self.root) as db:
            self.assertEqual(_workflow_proposal(db, proposal['id'])['status'], 'pending')

    def test_exact_host_paths_origin_and_live_revocation(self):
        code, _, html = self.request()
        self.assertEqual(code, 200)
        self.assertIn(b'data-crm-public-access="read-only"', html)
        self.assertEqual(self.request('/apps/crm/assets/app.js')[0], 200)
        for path in ('/api/apps/chat/backend', '/api/auth/session', '/data/crm.sqlite', '/apps/crm/widgets/crm-external-settings/', '/apps/crm/assets/../index.html', '/apps/crm/assets/%2e%2e/x', '//evil.test/', 'https://evil.test/'):
            self.assertGreaterEqual(self.request(path)[0], 400, path)
        self.assertEqual(self.request(host='maverick.example.test')[0], 404)
        for origin in ('null', 'https://sibling.apps.maverick.example.test', ''):
            self.assertEqual(self.request('/api/apps/crm/backend', 'POST', {'action': 'bootstrap'}, headers={'origin': origin, 'content-type': 'application/json'})[0], 403)
        self.assertEqual(self.request('/api/apps/crm/backend', 'POST', {'action': 'bootstrap'})[0], 200)
        atomic_json(self.root / 'external-hosting/access.json', {**self.access, 'enabled': False})
        self.assertEqual(self.request('/apps/crm/assets/app.js')[0], 404)
        atomic_json(self.root / 'external-hosting/access.json', self.access)
        atomic_json(self.projection, {'expires': 0})
        self.assertEqual(self.request()[0], 404)

    def test_hosting_controls_require_real_human_admin_and_revision(self):
        body = {'action': 'crm.external.configure', 'enabled': True, 'access': 'read-write', 'expected_revision': 1, 'confirm': True}
        actor = {'user_id': 'owner', 'workspace_role': 'owner', 'surface': 'backend'}
        for changes in ({'surface': 'cli'}, {'runtime_session_id': 'agent'}, {'workspace_role': 'member'}, {'user_id': ''}):
            with self.assertRaises(CrmError):
                configure(self.root, body, actor={**actor, **changes})
        result = configure(self.root, body, actor=actor)
        self.assertEqual(result['revision'], 2)
        self.assertEqual(result['access'], 'read-write')
        self.assertFalse(result['ready'])
        with self.assertRaises(CrmError):
            configure(self.root, body, actor=actor)
        self.assertEqual(self.request()[0], 404)  # Old child cannot retain authority.
        self.assertEqual(status(self.root)['url'], 'https://crm.apps.maverick.example.test')
        for domain in ('https://maverick.test', '127.0.0.1', 'example.test/path', '-bad.test', 'Example.test'):
            with self.assertRaises(CrmError):
                hostname(domain)

    @unittest.skipUnless(os.environ.get('CRM_PUBLIC_CONFINEMENT_TEST') == '1', 'explicit Linux confinement proof')
    def test_real_confinement_reads_native_crm_without_core_or_write_authority(self):
        listener = self.base / 'listener'; listener.mkdir()
        args = command(app=APP, data=self.root, state=self.projection.parent,
                       listener=listener, host=self.runtime.hostname, access='read-only')
        # Exercise the actual closure with a bounded child; no detached service.
        index = args.index('/usr/bin/python3', args.index('--chdir'))
        script = '''
import sys, socket
from pathlib import Path
sys.path[:0] = ['/app', '/app/backend']
from public_server.policy import execute
assert execute('/data', {'action':'bootstrap'}, access='read-only')[1]['contacts'][0]['display_name'] == 'Public contact'
assert not Path('/home').exists() and not Path('/sdk/core/api').exists()
try:
 Path('/data/forbidden').write_text('no')
 raise AssertionError('writable read-only mount')
except OSError: pass
try:
 socket.create_connection(('127.0.0.1',8014), timeout=.2)
 raise AssertionError('host network accessible')
except OSError: pass
print('confined CRM read passed')
'''
        result = subprocess.run(args[:index] + ['/usr/bin/python3', '-B', '-c', script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('confined CRM read passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
