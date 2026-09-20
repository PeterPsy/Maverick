"""The public runtime's lease follows canonical workspace and app authority."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
import crm_public_supervisor as supervisor


class SupervisorAuthorityTest(unittest.TestCase):
    def setUp(self):
        self.config = {'workspace_id': 'test-public', 'installation_domain': 'maverick.example.test'}
        self.data = ROOT / 'workspaces/test-public/data/crm'
        self.binding = SimpleNamespace(status='enabled', source_kind='platform', data_root=str(self.data))
        self.apps = Mock(get_workspace_app_binding=Mock(return_value=self.binding))
        self.workspace = SimpleNamespace(status='active')
        self.workspaces = Mock(get_workspace=Mock(return_value=self.workspace))
        self.stack = []
        for name, result in (
            ('resolve_workspace_app_surface', (ROOT / 'apps/crm', None)),
            ('deployment', {'hostname': 'crm.apps.maverick.example.test'}),
            ('settings', {'enabled': True, 'access': 'read-only', 'revision': 1}),
        ):
            p = patch.object(supervisor, name, return_value=result)
            self.stack.append(p.start()); self.addCleanup(p.stop)

    def test_exact_source_and_workspace_are_required(self):
        self.assertEqual(supervisor.authority(self.apps, self.workspaces, self.config)[0], self.data)
        self.workspace.status = 'closed'
        with self.assertRaises(ValueError):
            supervisor.authority(self.apps, self.workspaces, self.config)
        self.workspace.status = 'active'; self.binding.status = 'disabled'
        with self.assertRaises(ValueError):
            supervisor.authority(self.apps, self.workspaces, self.config)
        self.binding.status = 'enabled'; self.binding.data_root = str(ROOT / 'workspaces/other/data/crm')
        with self.assertRaises(ValueError):
            supervisor.authority(self.apps, self.workspaces, self.config)
        self.binding.data_root = str(self.data)
        self.stack[0].return_value = (ROOT / 'apps/mail', None)
        with self.assertRaises(ValueError):
            supervisor.authority(self.apps, self.workspaces, self.config)

    def test_disable_and_domain_change_revoke_the_lease(self):
        self.stack[2].return_value = {'enabled': False, 'access': 'read-only', 'revision': 2}
        with self.assertRaises(ValueError):
            supervisor.authority(self.apps, self.workspaces, self.config)
        self.stack[2].return_value = {'enabled': True, 'access': 'read-only', 'revision': 2}
        self.stack[1].return_value = {'hostname': 'crm.apps.other.example'}
        with self.assertRaises(ValueError):
            supervisor.authority(self.apps, self.workspaces, self.config)


if __name__ == '__main__':
    unittest.main()
