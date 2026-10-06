"""Background native generation has an auth-only home and no tool surfaces."""
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.providers.background_text import generate_background_text
from core.providers.errors import ProviderError
from core.shared.entrypoints import EntrypointShutdownController


class BackgroundTextTests(unittest.TestCase):
    def test_private_home_environment_schema_usage_and_inherited_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'source-home'
            source.mkdir()
            (source/'auth.json').write_text('{"fixture":true}')
            (source/'config.toml').write_text('[mcp_servers.private]\ncommand="unsafe"\n')
            executable=root/'codex'
            executable.write_text(f'#!{sys.executable}\n'+'''import sys, os, json
if '--version' in sys.argv:
    print('codex-cli 0.159.2'); sys.exit(0)
home=os.environ['CODEX_HOME']
assert json.load(open(home+'/auth.json'))=={'fixture':True}
assert not os.path.exists(home+'/config.toml')
assert 'PRIVATE_TEST_SECRET' not in os.environ
assert not os.path.exists(home+'/skills')
assert any('"shell_tool" = false' in x for x in sys.argv)
assert any('"code_mode_host" = false' in x for x in sys.argv)
assert 'web_search="disabled"' in sys.argv
assert os.readlink('/proc/self/fd/3').endswith('/gate')
assert 'untrusted fixture' in sys.stdin.read()
json.load(open(sys.argv[sys.argv.index('--output-schema')+1]))
open(sys.argv[sys.argv.index('-o')+1],'w').write('{"memory":[],"improvements":[]}')
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':11,'output_tokens':3}}))
''')
            executable.chmod(0o755)
            definition=SimpleNamespace(provider_id='codex',default_model_family='fixture-model',model_options=[SimpleNamespace(model_id='fixture-model')])
            state=SimpleNamespace(provider_store=object())
            request={'system_prompt':'Return JSON','input_text':'untrusted fixture','output_schema':{'type':'object'},'timeout_seconds':10,'max_output_tokens':128}
            with (root/'gate').open('a+') as gate, patch.dict(os.environ,{'MAVERICK_CODEX_COMMAND':str(executable),'MAVERICK_CODEX_HOME':str(source),'PRIVATE_TEST_SECRET':'must not propagate'}), patch('core.providers.background_text.resolve_provider_for_workspace',return_value=(definition,None)):
                # Descriptor numbers vary under the test runner; pass it to the fixture assertion.
                script=executable.read_text().replace("'/proc/self/fd/3'",repr('/proc/self/fd/'+str(gate.fileno())))
                executable.write_text(script)
                result=generate_background_text(state,workspace_id='default',app_id='consumer',request=request,controller=EntrypointShutdownController(),lock_fd=gate.fileno())
            self.assertEqual(result['usage']['total_tokens'],14)
            self.assertEqual(result['model_id'],'fixture-model')
            self.assertEqual(json.loads(result['output_text']),{'memory':[],'improvements':[]})

    def test_non_native_workspace_provider_is_rejected(self):
        with patch('core.providers.background_text.resolve_provider_for_workspace',return_value=(SimpleNamespace(provider_id='other'),None)):
            with self.assertRaises(ProviderError):
                generate_background_text(SimpleNamespace(provider_store=object()),workspace_id='default',app_id='consumer',request={},controller=EntrypointShutdownController(),lock_fd=-1)
