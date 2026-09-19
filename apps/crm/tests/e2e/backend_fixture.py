"""Browser fixture: real CRM and provider backends in an isolated temporary workspace."""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, 'apps/crm/backend')
from service import handle_action
from errors import CrmError, error_payload

request = json.load(sys.stdin)
root = Path(request['root'])
providers = request.get('providers', {})
dependencies = {'dependencies': [{'alias': alias, 'selected_provider_app_ids': [app]} for alias, app in providers.items()]}
body = {**request['body'], '_app_dependencies': dependencies}


def provider_request(app, provider_body, surface):
    workspace = root / 'providers'
    for path in ('storage/uploaded', 'storage/generated', 'data/' + app):
        (workspace / path).mkdir(parents=True, exist_ok=True)
    raw = {'surface': surface, 'app_id': app, 'workspace_id': 'browser-fixture',
           'data_root': str(workspace / 'data' / app), 'workspace_root': str(workspace),
           'uploaded_storage_root': str(workspace / 'storage/uploaded'), 'generated_storage_root': str(workspace / 'storage/generated'),
           'effective_mode': 'full-access', 'body': provider_body}
    result = subprocess.run([sys.executable, f'apps/{app}/backend/app_backend.py'], input=json.dumps(raw), capture_output=True,
                            text=True, check=True, timeout=15, env={**os.environ, 'PYTHONPATH': str(Path.cwd())})
    return json.loads(result.stdout)


try:
    status, result = handle_action(root, body.get('action', 'bootstrap'), body)
    for action in result.get('dependency_backend_requests', []):
        app = providers[action['dependency_alias']]
        if app in {'calendar', 'mail', 'speech'}:
            preflight = provider_request(app, action['body'], 'secret_selector')
            assert not preflight.get('requires_secrets'), 'Browser fixtures never access provider credentials.'
        response = provider_request(app, action['body'], 'dependency_backend')
        callback = action['callback']
        handle_action(root, callback['action'], {**callback['payload'], '_trusted_surface': 'dependency_backend_request_callback',
            '_app_dependencies': dependencies, 'request_id': action['request_id'], 'dependency_alias': action['dependency_alias'],
            'dependency_backend_status': 'completed', 'dependency_backend_result': {**response, 'dependency_provider_app_id': app}})
except CrmError as error:
    status, result = error.status_code, error_payload(error)
print(json.dumps({'status': status, 'body': result}))
