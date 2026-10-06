"""Generic generation locks span workspaces, callbacks and cancellation."""
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import fcntl
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.apps.background_generation import apply_background_generation_requests, validate_request
from core.apps.errors import AppHostingError
from core.shared.entrypoints import EntrypointShutdownController


class BackgroundGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.owner = EntrypointShutdownController()
        self.addCleanup(self.owner.begin_shutdown)
        self.state = SimpleNamespace(repository_root=Path(self.temp.name), background_generation_shutdown_controller=self.owner)
        self.parsed = SimpleNamespace(contract=SimpleNamespace(permissions=SimpleNamespace(runtime=SimpleNamespace(create_sessions=True))))

    def request(self, key='analysis', token='attempt-1'):
        return {'request_id':token, 'exclusive_key':key,'input_text':'evidence','system_prompt':'Return JSON',
                'output_schema':{'type':'object'},'callback':{'action':'done','payload':{}}}

    def apply(self, result, workspace='default', app_id='consumer'):
        apply_background_generation_requests(self.state, result=result, workspace_id=workspace, app_id=app_id,
            source_root=Path(self.temp.name), backend_entrypoint='backend.py', data_root=str(Path(self.temp.name)/workspace),
            parsed=self.parsed, start_path=Path(self.temp.name))

    def test_global_slot_is_held_during_inference_callback_and_cancellation(self):
        entered, release_generation, callback_entered, release_callback, finished = (Event() for _ in range(5))
        callbacks = []
        def generation(*args, **kwargs):
            entered.set()
            self.assertTrue(release_generation.wait(5))
            return {'output_text':'{}'}
        def callback(context, request, output):
            callbacks.append((context['workspace_id'], output['status']))
            if output['status'] != 'busy':
                callback_entered.set()
                self.assertTrue(release_callback.wait(5))
                finished.set()
        with patch('core.apps.background_generation.generate_background_text', side_effect=generation), patch('core.apps.background_generation._callback', side_effect=callback):
            try:
                self.apply({'background_generation_requests':[self.request()]})
                self.assertTrue(entered.wait(5))
                self.apply({'background_generation_requests':[self.request(token='attempt-2')]},workspace='other')
                self.assertIn(('other','busy'),callbacks)
                self.apply({'background_generation_cancel_requests':['attempt-1']})
                self.apply({'background_generation_requests':[self.request(token='attempt-3')]},workspace='third')
                self.assertIn(('third','busy'),callbacks)
                release_generation.set()
                self.assertTrue(callback_entered.wait(5))
                self.apply({'background_generation_requests':[self.request(token='attempt-4')]},workspace='fourth')
                self.assertIn(('fourth','busy'),callbacks)
                self.assertIn(('default','cancelled'),callbacks)
            finally:
                release_generation.set()
                release_callback.set()
                self.assertTrue(finished.wait(5))

    def test_inherited_lock_survives_parent_handle_closure(self):
        lock_path = Path(self.temp.name)/'gate'
        parent = lock_path.open('a+')
        fcntl.flock(parent.fileno(), fcntl.LOCK_EX|fcntl.LOCK_NB)
        child = subprocess.Popen([sys.executable,'-c','import sys; print("ready", flush=True); sys.stdin.read()'],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, pass_fds=(parent.fileno(),))
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready')
            parent.close()
            with lock_path.open('a+') as contender:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(contender.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                child.communicate(input='',timeout=5)
                fcntl.flock(contender.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        finally:
            parent.close()
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)

    def test_app_scope_cancellation_cannot_cancel_another_workspace(self):
        controller = EntrypointShutdownController()
        with patch.dict('core.apps.background_generation._active', {('other','consumer','attempt-1'):controller},clear=True):
            self.apply({'background_generation_cancel_requests':['attempt-1']})
            self.assertFalse(controller.is_shutting_down())

    def test_no_backend_lifecycle_owner_fails_without_detached_work(self):
        self.state.background_generation_shutdown_controller=None
        with patch('core.apps.background_generation._callback') as callback, patch('core.apps.background_generation.generate_background_text') as generate:
            self.apply({'background_generation_requests':[self.request()]})
            generate.assert_not_called()
            self.assertEqual(callback.call_args.args[2]['error'],'background_host_unavailable')

    def test_revoked_app_admission_skips_inference(self):
        finished = Event()
        request = {**self.request(), 'admission': {'action':'admit'}}
        with patch('core.apps.background_generation._invoke_app', return_value={'json':{'allowed':False}}), patch('core.apps.background_generation.generate_background_text') as generate, patch('core.apps.background_generation._callback', side_effect=lambda *args: finished.set()) as callback:
            self.apply({'background_generation_requests':[request]})
            self.assertTrue(finished.wait(5))
            generate.assert_not_called()
            self.assertEqual(callback.call_args.args[2]['status'], 'cancelled')

    def test_request_shape_and_permission_are_enforced(self):
        self.parsed.contract.permissions.runtime.create_sessions=False
        with self.assertRaises(AppHostingError):
            self.apply({'background_generation_requests':[self.request()]})
        for changes in [{'input_text':'x'*100001},{'max_output_tokens':True},{'timeout_seconds':1},{'model_id':{}}, {'callback':{'action':[]}}, {'model_source':'unknown'}]:
            with self.subTest(changes=changes), self.assertRaises(AppHostingError):
                validate_request({**self.request(),**changes})
