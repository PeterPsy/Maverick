"""Explicit, one-shot Usage cutover before the managed backend starts accepting work.

This operator entry point runs only with a stopped systemd backend, normally as
an explicitly installed ExecStartPre. It never runs from ordinary bootstrap,
request handling, or a store read. A completed receipt prevents later restarts
from repeating the migration, including after an intentional rollback.
"""

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess

from core.usage.administration import usage_migration
from core.usage.handoff import USAGE_ROOT, active_adapter, atomic_json, selected_adapter, usage_fence


def require_stopped_backend(service_name: str) -> dict[str, str]:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]*\.service', service_name):
        raise ValueError('Expected a systemd service name.')
    result = subprocess.run(['systemctl', 'show', service_name, '--property=MainPID,ControlPID,ActiveState,SubState,KillMode'],
        capture_output=True, text=True, check=True)
    status = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    stopped = status.get('ActiveState') in {'inactive', 'failed'} and status.get('ControlPID') == '0'
    own_prestart = (status.get('ActiveState') == 'activating' and status.get('SubState') == 'start-pre'
        and status.get('ControlPID') == str(os.getpid()))
    if status.get('MainPID') != '0' or status.get('KillMode') != 'control-group' or not (stopped or own_prestart):
        raise RuntimeError('Usage startup cutover requires the stopped backend and its drained control group.')
    return status


def run_startup_cutover(repository_root: Path, receipt: Path, *, service_name: str = 'maverick-core.service') -> dict:
    """Prepare/validate/promote/back up with all backend producers stopped."""
    repository_root = repository_root.resolve(strict=True)
    receipt = receipt.resolve()
    root = repository_root / USAGE_ROOT
    if not receipt.is_relative_to(root / 'maintenance'):
        raise ValueError('The operator receipt must be under the Usage owner maintenance directory.')
    status = require_stopped_backend(service_name)
    try:
        progress = json.loads(receipt.read_text())
    except FileNotFoundError:
        progress = {'schema': 1, 'owner': 'usage', 'target_adapter': 'sqlite', 'status': 'pending',
            'created_at': datetime.now(UTC).isoformat()}
    if (progress.get('schema') != 1 or progress.get('owner') != 'usage'
            or progress.get('target_adapter') != 'sqlite'):
        raise RuntimeError('Unsupported Usage startup maintenance receipt.')
    if progress.get('status') == 'completed':
        return progress
    if selected_adapter() != 'sqlite':
        raise RuntimeError('Configure MAVERICK_USAGE_STORE=sqlite for the next backend before cutover.')
    with usage_fence(root, exclusive=True):
        receipt.parent.mkdir(mode=0o2770, parents=True, exist_ok=True)
        progress['service_state'] = status
        migration_id = progress.get('prepared', {}).get('migration_id')
        if active_adapter(root) == 'sqlite':
            marker = json.loads((root / 'store.json').read_text())
            if not migration_id or marker.get('migration_id') != migration_id:
                raise RuntimeError('Another Usage migration is active; this startup request cannot adopt it.')
        elif not migration_id:
            progress['prepared'] = usage_migration(repository_root, {'phase': 'prepare'})
            migration_id = progress['prepared']['migration_id']
            progress['status'] = 'prepared'
            atomic_json(receipt, progress)
        progress['validated'] = usage_migration(repository_root, {'phase': 'validate', 'migration_id': migration_id})
        progress['cutover'] = usage_migration(repository_root, {'phase': 'cutover', 'migration_id': migration_id})
        progress['status'] = 'promoted'
        atomic_json(receipt, progress)
        progress['backup'] = usage_migration(repository_root, {'phase': 'backup'})
        progress['status'] = 'completed'
        progress['completed_at'] = datetime.now(UTC).isoformat()
        atomic_json(receipt, progress)
    return progress


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository-root', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True, help='Unique receipt under data/control-plane/usage/maintenance/')
    parser.add_argument('--service-name', default='maverick-core.service')
    args = parser.parse_args()
    print(json.dumps(run_startup_cutover(args.repository_root, args.receipt, service_name=args.service_name), indent=2))


if __name__ == '__main__':
    main()
