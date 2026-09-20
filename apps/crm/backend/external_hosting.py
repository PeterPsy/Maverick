"""CRM-owned publication controls. Never reachable through the public adapter."""
import fcntl
import json
from pathlib import Path
import re
import time
from uuid import uuid4

from errors import CrmError, ValidationError


class HostingDenied(CrmError):
    code = 'hosting_forbidden'
    status_code = 403


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, sort_keys=True) + '\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def hostname(domain):
    if not isinstance(domain, str) or len(domain) > 230 or domain != domain.lower():
        raise ValidationError('Invalid installation hostname.')
    labels = domain.split('.')
    if len(labels) < 2 or labels[-1].isdigit() or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels):
        raise ValidationError('Use the installation DNS hostname, without a scheme or path.')
    return 'crm.apps.' + domain


def settings(root):
    path = Path(root) / 'external-hosting' / 'access.json'
    if not path.exists():
        return {'enabled': False, 'access': 'read-only', 'revision': 0}
    value = json.loads(path.read_text())
    if (type(value.get('enabled')) is not bool or value.get('access') not in {'read-only', 'read-write'}
            or type(value.get('revision')) is not int or value['revision'] < 0):
        raise ValidationError('Invalid public access settings.')
    return value


def deployment(root):
    value = json.loads((Path(root) / 'external-hosting' / 'deployment.json').read_text())
    return {'hostname': hostname(value['installation_domain'])}


def status(root):
    result = {'ok': True, **settings(root), 'configured': False, 'ready': False}
    try:
        result.update(configured=True, url='https://' + deployment(root)['hostname'])
        state = json.loads((Path(root) / 'external-hosting' / 'status.json').read_text())
        result['ready'] = bool(result['enabled'] and state.get('revision') == result['revision']
                               and time.time() < state.get('expires', 0) <= time.time() + 10)
    except (OSError, ValueError, KeyError, CrmError):
        pass
    return result


def configure(root, body, *, actor):
    if (not actor.get('user_id') or actor.get('surface') != 'backend' or actor.get('runtime_session_id')
            or not (actor.get('platform_role') == 'admin' or actor.get('workspace_role') in {'owner', 'admin'})):
        raise HostingDenied('Only an authenticated administrator can change public CRM access in Settings.')
    if set(body) != {'action', 'enabled', 'access', 'expected_revision', 'confirm'} or body.get('confirm') is not True:
        raise ValidationError('Review and confirm the public access setting.')
    if type(body.get('enabled')) is not bool or body.get('access') not in {'read-only', 'read-write'} or type(body.get('expected_revision')) is not int:
        raise ValidationError('Invalid public access setting.')
    deployment(root)  # Only an operator supplies the installation hostname.
    directory = Path(root) / 'external-hosting'
    with (directory / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = settings(root)
        if current['revision'] != body['expected_revision']:
            raise ValidationError('Settings changed. Refresh before confirming again.')
        atomic_json(directory / 'access.json', {
            'enabled': body['enabled'], 'access': body['access'], 'revision': current['revision'] + 1,
            'updated_by': actor['user_id'], 'updated_at': time.time(),
        })
    return status(root)


def handle(root, body, envelope):
    if not envelope.user_id:
        raise HostingDenied('Authentication required.')
    if body.get('action') == 'crm.external.status':
        return 200, status(root)
    actor = {key: getattr(envelope, key, '') for key in ('user_id', 'platform_role', 'workspace_role', 'runtime_session_id')}
    actor['surface'] = envelope.raw.get('surface', '')
    return 200, configure(root, body, actor=actor)
