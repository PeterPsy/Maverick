"""Operator-managed foreground CRM public runtime; never boots or restarts Core."""
import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

REPOSITORY = Path(__file__).resolve().parents[1]
APP = REPOSITORY / 'apps/crm'
sys.path.insert(0, str(REPOSITORY))
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / 'backend'))

from core.api.control_store import ControlStoreSettings, build_control_plane_collections
from core.apps.store import AppDocumentStore
from core.apps.surfaces import resolve_workspace_app_surface
from core.workspaces.store import WorkspaceDocumentStore
from external_hosting import atomic_json, deployment, hostname, settings
from public_server.confinement import command


def authority(apps, workspaces, config):
    workspace = config['workspace_id']
    if workspaces.get_workspace(workspace).status != 'active':
        raise ValueError('workspace_inactive')
    binding = apps.get_workspace_app_binding(workspace_id=workspace, app_id='crm')
    if binding.status != 'enabled' or binding.source_kind != 'platform':
        raise ValueError('crm_inactive')
    source, _contract = resolve_workspace_app_surface(apps, binding=binding, start_path=REPOSITORY)
    if source.resolve() != APP.resolve():
        raise ValueError('crm_source_changed')
    data = Path(binding.data_root)
    if data != REPOSITORY / 'workspaces' / workspace / 'data/crm' or any(p.is_symlink() for p in (data, *data.parents)):
        raise ValueError('crm_data_changed')
    host = hostname(config['installation_domain'])
    if deployment(data)['hostname'] != host:
        raise ValueError('crm_deployment_changed')
    access = settings(data)
    if not access['enabled']:
        raise ValueError('crm_public_disabled')
    return data, host, access


def stop_child(child):
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def run(config, apps, workspaces):
    state, listener = (Path(config[key]) for key in ('state_directory', 'listener_directory'))
    for path in (state, listener):
        if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)) or REPOSITORY in path.parents:
            raise ValueError('unsafe_service_directory')
        path.mkdir(mode=0o750, parents=True, exist_ok=True)
    if state == listener or state in listener.parents or listener in state.parents:
        raise ValueError('distinct_service_directories_required')
    projection = state / 'authority.json'
    child, previous, stopping = None, None, False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while not stopping:
            try:
                data, host, access = authority(apps, workspaces, config)
                signature = (str(data), host, access['access'], access['revision'])
                if signature != previous or child is None or child.poll() is not None:
                    atomic_json(projection, {'expires': 0})
                    stop_child(child)
                    socket = listener / 'public.sock'
                    if socket.exists():
                        if not socket.is_socket():
                            raise ValueError('unsafe_socket_path')
                        socket.unlink()
                    child = subprocess.Popen(command(app=APP, data=data, state=state,
                        listener=listener, host=host, access=access['access']),
                        env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}, stdin=subprocess.DEVNULL)
                    previous = signature
                # A socket probe, not process presence, establishes readiness.
                if not healthy(listener / 'public.sock'):
                    atomic_json(projection, {'expires': 0})
                else:
                    value = {'hostname': host, 'revision': access['revision'], 'expires': time.time() + 8}
                    atomic_json(projection, value)
                    atomic_json(data / 'external-hosting/status.json', value)
            except Exception as error:
                atomic_json(projection, {'expires': 0})
                stop_child(child)
                child, previous = None, None
                # No request data or credentials in the journal.
                if not isinstance(error, ValueError):
                    print('CRM publication unavailable: ' + type(error).__name__, flush=True)
            time.sleep(2)
    finally:
        atomic_json(projection, {'expires': 0})
        stop_child(child)


def healthy(path):
    import socket
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(1)
            sock.connect(str(path))
            sock.sendall(b'HEAD / HTTP/1.0\r\nHost: invalid\r\n\r\n')
            return sock.recv(128).startswith(b'HTTP/1.0 404')
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    collections = build_control_plane_collections(ControlStoreSettings.from_environment(repository_root=REPOSITORY))
    run(config, AppDocumentStore(collections.apps), WorkspaceDocumentStore(collections.workspace))


if __name__ == '__main__':
    main()
