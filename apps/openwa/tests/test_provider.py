"""Root-source paths, trusted maintenance and restart/stop recovery regressions."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import json
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / 'provider'))
sys.path.insert(0, str(APP_ROOT / 'backend'))
import local_gateway
import provider_service
from gateway import GatewayError

spec = importlib.util.spec_from_file_location('openwa_provider_cli', APP_ROOT / 'cli/provider_cli.py')
provider_cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider_cli)
spec = importlib.util.spec_from_file_location('openwa_provider_hook', APP_ROOT / 'hooks/provider_recovery.py')
provider_hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider_hook)


class ProviderTests(unittest.TestCase):
    def test_root_source_keeps_provider_data_in_the_workspace(self):
        self.assertEqual(local_gateway.DATA_ROOT, APP_ROOT.parents[1] / 'workspaces/default/data/openwa/gateway')
        self.assertEqual(local_gateway.SOURCE_ROOT, APP_ROOT / 'provider/upstream')

    def test_linking_an_existing_account_does_not_enable_new_account_send_caps(self):
        environment = local_gateway.environment()
        self.assertEqual(environment['SEND_PACING_ENABLED'], 'false')
        self.assertNotIn('RATE_LIMIT_SHORT_LIMIT', environment)
        self.assertNotIn('RATE_LIMIT_MEDIUM_LIMIT', environment)
        self.assertNotIn('RATE_LIMIT_LONG_LIMIT', environment)

    def test_only_trusted_default_workspace_admin_can_manage_provider(self):
        payload = SimpleNamespace(user_id='admin', platform_role='admin', workspace_id='default',
                                  data_root=str(APP_ROOT.parents[1] / 'workspaces/default/data/openwa'),
                                  arguments={'action': 'start'})
        with patch.object(provider_cli, 'operate', return_value={'ok': True}) as operate:
            self.assertTrue(provider_cli.handle_provider(payload)['ok'])
            operate.assert_called_once_with('start')
            for field, value in [('user_id', None), ('platform_role', 'member'),
                                 ('workspace_id', 'other'), ('data_root', '/tmp/other')]:
                original = getattr(payload, field)
                setattr(payload, field, value)
                operate.reset_mock()
                self.assertEqual(provider_cli.handle_provider(payload)['status_code'], 403)
                operate.assert_not_called()
                setattr(payload, field, original)

    def test_cli_routes_provider_command_before_whatsapp_status(self):
        payload = SimpleNamespace(raw={'command_id': 'app.openwa.provider'}, user_id=None,
                                  platform_role='admin', workspace_id='default')
        with patch('core.app_sdk.runtime.read_entrypoint_payload', return_value=payload), \
             patch('core.app_sdk.runtime.emit_json') as emit, self.assertRaises(SystemExit) as exit:
            runpy.run_path(str(APP_ROOT / 'cli/app_cli.py'), run_name='__main__')
        self.assertEqual(exit.exception.code, 0)
        self.assertEqual(emit.call_args.args[0]['status_code'], 403)
        self.assertNotIn('connection', emit.call_args.args[0])

    def test_status_does_not_start_a_dead_supervisor_or_hide_provider_outage(self):
        with tempfile.TemporaryDirectory() as root, patch.object(provider_service, 'CONTROL', Path(root) / 'control.json'), \
             patch.object(provider_service, '_daemon_alive', return_value=False), \
             patch.object(provider_service, '_run') as run, \
             patch.object(provider_service, 'check_readiness', side_effect=GatewayError('Unavailable', 503)):
            status = provider_service.status()
            self.assertFalse(status['running'])
            self.assertFalse(status['ready'])
            self.assertFalse(status['recovery_enabled'])
            run.assert_not_called()
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_recovery_restarts_after_supervisor_loss_and_respects_persisted_stop(self):
        with tempfile.TemporaryDirectory() as root, patch.object(provider_service, 'APP_DATA', Path(root)), \
             patch.object(provider_service, 'CONTROL', Path(root) / 'control.json'), \
             patch.object(provider_service, '_start', return_value=True) as start:
            provider_service._set_recovery(True)
            self.assertTrue(provider_service.ensure_running()['started'])
            start.assert_called_once()
            start.reset_mock()
            provider_service._set_recovery(False)
            self.assertFalse(provider_service.ensure_running()['started'])
            start.assert_not_called()
            self.assertEqual(json.loads(provider_service.CONTROL.read_text()), {'version': 1, 'enabled': False})

    def test_stop_persists_intent_before_stopping_only_the_owned_process(self):
        with tempfile.TemporaryDirectory() as root, patch.object(provider_service, 'APP_DATA', Path(root)), \
             patch.object(provider_service, 'CONTROL', Path(root) / 'control.json'), \
             patch.object(provider_service, '_process', return_value={'name': provider_service.NAME}), \
             patch.object(provider_service, 'status', return_value={}), patch.object(provider_service, '_run') as run:
            provider_service._set_recovery(True)
            def stopped(args):
                self.assertFalse(provider_service.recovery_enabled())
                self.assertEqual(args, ['stop', provider_service.NAME])
            run.side_effect = stopped
            self.assertTrue(provider_service.operate('stop')['ok'])
            run.assert_called_once()

    def test_uninitialized_provider_never_creates_or_resets_a_database(self):
        with tempfile.TemporaryDirectory() as root, patch.object(provider_service, 'DATA_ROOT', Path(root)), \
             patch.object(provider_service, '_run') as run:
            with self.assertRaises(provider_service.ProviderServiceError):
                provider_service._start()
            run.assert_not_called()
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_hook_cannot_start_another_workspace_or_accept_a_frontend_invocation(self):
        payload = SimpleNamespace(raw={'surface': 'backend_recovery'}, workspace_id='default',
                                  data_root=str(APP_ROOT.parents[1] / 'workspaces/default/data/openwa'))
        with patch.object(provider_hook, 'ensure_running', return_value={'ok': True}) as ensure:
            self.assertTrue(provider_hook.recover(payload)['ok'])
            ensure.assert_called_once()
            ensure.reset_mock()
            payload.workspace_id = 'other'
            self.assertTrue(provider_hook.recover(payload)['skipped'])
            ensure.assert_not_called()
            payload.workspace_id = 'default'
            payload.raw['surface'] = 'backend'
            self.assertFalse(provider_hook.recover(payload)['ok'])
            ensure.assert_not_called()

    def test_supervisor_never_inherits_maverick_or_provider_credentials(self):
        with patch.object(provider_service.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='')) as run:
            provider_service._run(['pid', provider_service.NAME])
        environment = run.call_args.kwargs['env']
        self.assertEqual(set(environment), {'PATH', 'LANG', 'PM2_HOME'})
        self.assertEqual(environment['PM2_HOME'], str(provider_service.SUPERVISOR))


if __name__ == '__main__':
    unittest.main()
