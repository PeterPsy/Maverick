#!/usr/bin/env python3
"""Exercise performance lifecycles in authenticated, disposable app frames."""

import json
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import psutil

from pwa_shell_cache_smoke import ROOT, _local_environment, _free_port, _stop_server, _wait_for_health

sys.path[:0] = [str(ROOT), str(ROOT / 'apps/storage/backend')]

from tests.support.performance_fixtures import storage_files
from tests.support.performance_chat_fixture import seed_chat_history
from inventory_migration import prepare_inventory, cutover_inventory
import inventory_legacy


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='maverick-performance-browser-') as temporary:
        root = Path(temporary)
        repository = root / 'repository'
        repository.mkdir()
        for name in ('AGENTS.md', 'core', 'docs', 'packages', 'scripts'):
            (repository / name).symlink_to(ROOT / name, target_is_directory=(ROOT / name).is_dir())
        (repository / 'workspaces').mkdir()
        uploaded, generated, data = storage_files(repository / 'workspaces/default', 350, shape='flat')
        reading = generated / 'reading'
        reading.mkdir()
        for path in generated.glob('report-*.md'):
            path.rename(reading / path.name)
        inventory_legacy.sync_inventory(data, uploaded_root=uploaded, generated_root=generated)
        migration = prepare_inventory(data, uploaded_root=uploaded, generated_root=generated)
        cutover_inventory(data, migration['migration_id'], uploaded_root=uploaded, generated_root=generated)
        apps = repository / 'apps'
        apps.mkdir()
        for source in (ROOT / 'apps').iterdir():
            if source.name not in {'chat', 'storage'}:
                (apps / source.name).symlink_to(source, target_is_directory=source.is_dir())
                continue
            destination = apps / source.name
            shutil.copytree(source, destination, ignore=shutil.ignore_patterns(
                'node_modules', '__pycache__', '.pytest_cache', 'tests', 'test-results', 'playwright-report'))
            contract_path = destination / 'app_contract.json'
            contract = json.loads(contract_path.read_text())
            contract['presentation']['frontend_resumable'] = True
            contract_path.write_text(json.dumps(contract))
        chat_fixture = seed_chat_history(repository)
        env = _local_environment(root, 'fixture-admin', 'fixture-only-password')
        env['MAVERICK_PERFORMANCE_BROWSER_FIXTURE'] = '1'
        env['MAVERICK_USAGE_STORE'] = 'document'
        port = _free_port()
        with (root / 'host.log').open('wb') as log:
            server = subprocess.Popen([sys.executable, str(ROOT / 'scripts/pwa_smoke_host.py'),
                '--host', '127.0.0.1', '--port', str(port), '--repository-root', str(repository)],
                cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                try:
                    _wait_for_health(port, server)
                except Exception:
                    log.flush()
                    sys.stderr.write((root / 'host.log').read_text(errors='replace')[-8000:])
                    raise
                result = subprocess.run(['node', str(ROOT / 'scripts/performance_browser_probe.mjs'),
                    f'http://maverick.localhost:{port}'], cwd=ROOT, env=env, check=False,
                    capture_output=True, text=True, timeout=360)
                sys.stderr.write(result.stderr)
                if result.returncode:
                    return result.returncode
                evidence = json.loads(result.stdout)
                evidence['chat_fixture'] = chat_fixture
                evidence['source_commit'] = subprocess.check_output(
                    ['git', '-c', f'safe.directory={ROOT}', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
                evidence['source_dirty'] = bool(subprocess.check_output(
                    ['git', '-c', f'safe.directory={ROOT}', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
                evidence['builds'] = {app: json.loads((ROOT / 'apps' / app / 'frontend/dist/maverick-frontend-assets.json').read_text())['build_id']
                    for app in ('base-shell', 'chat', 'storage', 'calendar')}
                evidence['python'] = platform.python_version()
                evidence['sqlite'] = sqlite3.sqlite_version
                print(json.dumps(evidence, indent=2))
                return 0
            finally:
                children = psutil.Process(server.pid).children(recursive=True) if server.poll() is None else []
                _stop_server(server)
                # Join only this disposable host's descendants before deleting its root.
                # A hook already accepted at shutdown can outlive the ASGI process.
                _, alive = psutil.wait_procs(children, timeout=5)
                for child in alive:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                _, alive = psutil.wait_procs(alive, timeout=5)
                for child in alive:
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                psutil.wait_procs(alive, timeout=5)


if __name__ == '__main__':
    raise SystemExit(main())
