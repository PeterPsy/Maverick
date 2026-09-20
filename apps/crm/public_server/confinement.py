"""No-network CRM runtime closure, independently revocable from Maverick."""
from pathlib import Path
import shutil
import sys
import sysconfig


def command(*, app, data, state, listener, host, access):
    python = Path(sys.executable).resolve()
    stdlib = Path(sysconfig.get_path('stdlib')).resolve()
    bwrap = shutil.which('bwrap')
    if not bwrap or sys.platform != 'linux' or not str(python).startswith('/usr/bin/') or not str(stdlib).startswith('/usr/lib/'):
        raise RuntimeError('supported_linux_confinement_required')
    for root in (app, data, state, listener):
        if not root.is_absolute() or not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
            raise RuntimeError('unsafe_runtime_path')
    if access not in {'read-only', 'read-write'}:
        raise RuntimeError('invalid_access')
    args = [bwrap, '--die-with-parent', '--unshare-all', '--cap-drop', 'ALL', '--clearenv',
            '--setenv', 'PATH', '/usr/bin', '--setenv', 'LANG', 'C.UTF-8',
            '--setenv', 'PYTHONDONTWRITEBYTECODE', '1', '--setenv', 'PYTHONNOUSERSITE', '1',
            '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
            '--dir', '/usr/bin', '--ro-bind', str(python), '/usr/bin/python3',
            '--ro-bind', str(stdlib), str(stdlib)]
    for path in (Path('/usr/lib/x86_64-linux-gnu'), Path('/usr/lib/aarch64-linux-gnu'), Path('/usr/lib64')):
        if path.is_dir():
            args += ['--ro-bind', str(path), str(path)]
    args += ['--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
             '--ro-bind', str(app / 'backend'), '/app/backend',
             '--ro-bind', str(app / 'public_server'), '/app/public_server',
             '--ro-bind', str(app / 'frontend/dist'), '/app/frontend/dist',
             '--ro-bind' if access == 'read-only' else '--bind', str(data), '/data',
             '--ro-bind', str(data / 'external-hosting'), '/data/external-hosting',
             '--ro-bind', str(state), '/state', '--bind', str(listener), '/listener',
             '--chdir', '/app', '/usr/bin/python3', '-B', '/app/public_server/server.py',
             '--root', '/data', '--assets', '/app/frontend/dist', '--projection', '/state/authority.json',
             '--hostname', host, '--access', access, '--socket', '/listener/public.sock']
    return args
