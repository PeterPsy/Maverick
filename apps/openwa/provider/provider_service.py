"""App-owned provider supervision and restart intent; no private profile inspection."""
from contextlib import contextmanager
from pathlib import Path
import fcntl
import json
import os
import socket
import subprocess
import tempfile
import time

from local_gateway import APP_ROOT, DATA_ROOT, SOURCE_ROOT, TOOLCHAINS, NODE
from gateway import GatewayError, check_readiness

NAME = 'loopino-openwa-default'
APP_DATA = DATA_ROOT.parent
SUPERVISOR = APP_DATA / 'supervisor'
CONTROL = APP_DATA / 'provider-control.json'
PM2 = TOOLCHAINS / 'pm2-7.0.4/node_modules/pm2/bin/pm2'


class ProviderServiceError(RuntimeError):
    pass


def _run(args):
    env = {'PATH': f'{NODE.parent}:{TOOLCHAINS}/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PM2_HOME': str(SUPERVISOR)}
    try:
        result = subprocess.run([str(NODE), str(PM2), *args], env=env, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        raise ProviderServiceError('The dedicated OpenWA supervisor could not be reached.') from None
    if result.returncode:
        raise ProviderServiceError('The dedicated OpenWA supervisor operation failed.')
    return result.stdout


def _daemon_alive():
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(1)
        try:
            client.connect(str(SUPERVISOR / 'rpc.sock'))
            return True
        except OSError:
            return False


def _process():
    if not _daemon_alive():
        return None
    try:
        rows = json.loads(_run(['jlist']))
    except (ValueError, TypeError):
        raise ProviderServiceError('The supervisor returned an invalid status.') from None
    if not isinstance(rows, list):
        raise ProviderServiceError('The supervisor returned an invalid status.')
    return next((row for row in rows if isinstance(row, dict) and row.get('name') == NAME), None)


def recovery_enabled():
    if CONTROL.is_symlink():
        raise ProviderServiceError('Provider control symlinks are not permitted.')
    if not CONTROL.exists():
        return False
    try:
        data = json.loads(CONTROL.read_text())
    except (ValueError, OSError):
        raise ProviderServiceError('The provider recovery setting could not be read.') from None
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('enabled'), bool):
        raise ProviderServiceError('The provider recovery setting is invalid.')
    return data['enabled']


def _set_recovery(enabled):
    if CONTROL.is_symlink():
        raise ProviderServiceError('Provider control symlinks are not permitted.')
    with tempfile.NamedTemporaryFile(mode='w', prefix='.provider-control-', dir=APP_DATA, delete=False) as control:
        temporary = Path(control.name)
        try:
            os.chmod(temporary, 0o600)
            json.dump({'version': 1, 'enabled': enabled}, control)
            control.flush()
            os.fsync(control.fileno())
            temporary.replace(CONTROL)
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def _lock():
    target = APP_DATA / '.provider-control.lock'
    if target.is_symlink():
        raise ProviderServiceError('Provider lock symlinks are not permitted.')
    with target.open('a') as lock:
        target.chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _initialized():
    if not (DATA_ROOT / 'main.sqlite').is_file():
        raise ProviderServiceError('This provider is not initialized. Bootstrap a fresh provider explicitly; never reset linked-device data.')
    if not (SOURCE_ROOT / 'dist/main.js').is_file():
        raise ProviderServiceError('The pinned OpenWA provider build is required.')


def _start(*, restart=False):
    _initialized()
    SUPERVISOR.mkdir(parents=True, exist_ok=True)
    SUPERVISOR.chmod(0o700)
    process = _process()
    script = str(APP_ROOT / 'provider/local_gateway.py')
    if process and process.get('pm2_env', {}).get('pm_exec_path') != script:
        _run(['delete', NAME])
        process = None
    if not process:
        _run(['start', script, '--name', NAME, '--interpreter', '/usr/bin/python3', '--cwd', str(APP_ROOT),
              '--max-memory-restart', '600M', '--restart-delay', '5000', '--time'])
        return True
    if restart or process.get('pm2_env', {}).get('status') != 'online':
        _run(['restart', NAME])
        return True
    return False


def status():
    process = _process()
    ready = False
    try:
        check_readiness('http://127.0.0.1:2785')
        ready = True
    except GatewayError:
        pass
    return {'supervisor': NAME, 'running': bool(process and process.get('pm2_env', {}).get('status') == 'online'),
            'ready': ready, 'recovery_enabled': recovery_enabled(), 'pid': int((process or {}).get('pid') or 0)}


def ensure_running():
    if not recovery_enabled():
        return {'ok': True, 'recovery_enabled': False, 'started': False}
    with _lock():
        # Recheck inside the lock: an explicit Stop always wins over recovery.
        if not recovery_enabled():
            return {'ok': True, 'recovery_enabled': False, 'started': False}
        return {'ok': True, 'recovery_enabled': True, 'started': _start()}


def operate(action):
    if action == 'status':
        return status()
    if action not in {'start', 'restart', 'stop'}:
        raise ProviderServiceError('Use start, status, restart or stop.')
    with _lock():
        if action == 'stop':
            _set_recovery(False)
            if _process():
                _run(['stop', NAME])
        else:
            _initialized()
            _set_recovery(True)
            _start(restart=action == 'restart')
    if action != 'stop':
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                check_readiness('http://127.0.0.1:2785')
                break
            except GatewayError:
                time.sleep(0.5)
        else:
            raise ProviderServiceError('OpenWA started but did not become ready. Check the dedicated provider status.')
    return {'ok': True, 'action': action, **status()}
