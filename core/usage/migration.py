"""Operator-owned Usage prepare, validate, cutover, backup, and reverse export."""

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from core.usage.handoff import USAGE_ROOT, active_adapter, atomic_json, selected_adapter, usage_fence
from core.usage.sqlite_store import UsageSqliteStore
from core.usage.transfer import (canonical_digest, digest, document_snapshot, import_snapshot,
    restore_document_snapshot, sqlite_snapshot, validate_database)


def usage_status(repository_root: Path) -> dict:
    root = repository_root / USAGE_ROOT
    adapter = active_adapter(root)
    result = {'owner': 'usage', 'adapter': adapter, 'configured_adapter': selected_adapter(),
        'path': str(USAGE_ROOT / 'usage.sqlite') if adapter == 'sqlite' else None,
        'sqlite_runtime': sqlite3.sqlite_version, 'restart_required': adapter != selected_adapter()}
    if adapter == 'sqlite':
        with usage_fence(root, expected=adapter), UsageSqliteStore(root / 'usage.sqlite').transaction() as connection:
            result['counts'] = {table: connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                for table in ('samples', 'streams', 'session_totals', 'buckets', 'quota_snapshots')}
    return result


def prepare(repository_root: Path, collections) -> dict:
    root = repository_root / USAGE_ROOT
    with usage_fence(root, expected='document', exclusive=True):
        _retire_after_rollback(root)
        snapshot = document_snapshot(collections)
        migration_id = 'usage-' + uuid4().hex
        folder = root / 'migrations' / migration_id
        folder.mkdir(parents=True)
        folder.chmod(0o2770)
        atomic_json(folder / 'source.json', snapshot)
        (folder / 'source.json').chmod(0o440)
        store = UsageSqliteStore(folder / 'usage.sqlite')
        store.initialize()
        import_snapshot(store, snapshot)
        verification = validate_database(store, expected_digest=canonical_digest(snapshot))
        manifest = {'schema': 1, 'migration_id': migration_id, 'created_at': datetime.now(UTC).isoformat(),
            'source_digest': digest(snapshot), 'canonical_digest': verification['digest'], 'counts': verification['counts'],
            'source_counts': {name: len(values) for name, values in snapshot.items()}, 'sqlite_runtime': sqlite3.sqlite_version}
        atomic_json(folder / 'manifest.json', manifest)
        return {**manifest, 'status': 'prepared'}


def _candidate(root: Path, migration_id: str):
    if not re.fullmatch(r'usage-[0-9a-f]{32}', migration_id):
        raise ValueError('Invalid Usage migration identity.')
    folder = root / 'migrations' / migration_id
    manifest = json.loads((folder / 'manifest.json').read_text())
    if manifest.get('schema') != 1 or manifest.get('migration_id') != migration_id:
        raise RuntimeError('Unsupported Usage migration manifest.')
    return folder, manifest, UsageSqliteStore(folder / 'usage.sqlite')


def validate(repository_root: Path, migration_id: str) -> dict:
    root = repository_root / USAGE_ROOT
    with usage_fence(root):
        _folder, manifest, store = _candidate(root, migration_id)
        return {'status': 'validated', **validate_database(store, expected_digest=manifest['canonical_digest'])}


def cutover(repository_root: Path, collections, migration_id: str) -> dict:
    root = repository_root / USAGE_ROOT
    with usage_fence(root, exclusive=True):
        _folder, manifest, store = _candidate(root, migration_id)
        if active_adapter(root) == 'sqlite':
            marker = json.loads((root / 'store.json').read_text())
            if marker.get('migration_id') != migration_id:
                raise RuntimeError('Another Usage migration is already active.')
            return {'status': 'already_active', 'adapter': 'sqlite', 'required_environment': {'MAVERICK_USAGE_STORE': 'sqlite'}}
        validate_database(store, expected_digest=manifest['canonical_digest'])
        if digest(document_snapshot(collections)) != manifest['source_digest']:
            raise RuntimeError('Usage source changed after prepare; drain producers and prepare again.')
        destination = root / 'usage.sqlite'
        if destination.exists():
            validate_database(UsageSqliteStore(destination), expected_digest=manifest['canonical_digest'])
        else:
            temporary = root / ('promotion-' + uuid4().hex + '.sqlite')
            try:
                store.backup(temporary)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        with UsageSqliteStore(destination).connection(write=True) as connection:
            if connection.execute('PRAGMA journal_mode=WAL').fetchone()[0] != 'wal':
                raise RuntimeError('Usage cutover requires WAL support.')
        atomic_json(root / 'store.json', {'schema': 1, 'adapter': 'sqlite', 'migration_id': migration_id})
        return {'status': 'cutover', 'adapter': 'sqlite', 'restart_required': True,
            'required_environment': {'MAVERICK_USAGE_STORE': 'sqlite'}}


def backup(repository_root: Path) -> dict:
    root = repository_root / USAGE_ROOT
    with usage_fence(root, expected='sqlite', exclusive=True):
        folder = _backup_folder(root)
        store = UsageSqliteStore(root / 'usage.sqlite')
        store.backup(folder / 'usage.sqlite')
        verification = validate_database(UsageSqliteStore(folder / 'usage.sqlite'))
        atomic_json(folder / 'manifest.json', {'schema': 1, 'owner': 'usage', **verification})
        return {'status': 'backed_up', 'owner': 'usage', 'path': str(folder.relative_to(repository_root)), **verification}


def repair(repository_root: Path) -> dict:
    """Back up and rebuild derived tables atomically under the owner's drain fence."""
    root = repository_root / USAGE_ROOT
    with usage_fence(root, expected='sqlite', exclusive=True):
        store = UsageSqliteStore(root / 'usage.sqlite')
        with store.connection() as connection:
            if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Usage source integrity validation failed.')
        source_digest = canonical_digest(sqlite_snapshot(store))
        folder = _backup_folder(root)
        store.backup(folder / 'usage.sqlite')
        manifest = {'schema': 1, 'owner': 'usage', 'operation': 'repair',
            'status': 'prepared', 'source_digest': source_digest}
        atomic_json(folder / 'manifest.json', manifest)
        store.rebuild_projections()
        verification = validate_database(store, expected_digest=source_digest)
        atomic_json(folder / 'manifest.json', {**manifest, 'status': 'repaired', **verification})
        return {'status': 'repaired', 'owner': 'usage',
            'backup': str(folder.relative_to(repository_root)), **verification}


def rollback(repository_root: Path, collections) -> dict:
    root = repository_root / USAGE_ROOT
    with usage_fence(root, exclusive=True):
        if active_adapter(root) == 'document':
            _retire_after_rollback(root)
            return {'status': 'already_rolled_back', 'required_environment': {'MAVERICK_USAGE_STORE': 'document'}}
        folder = _backup_folder(root)
        store = UsageSqliteStore(root / 'usage.sqlite')
        store.backup(folder / 'usage.sqlite')
        snapshot = sqlite_snapshot(store)
        verification = validate_database(store)
        atomic_json(folder / 'export.json', snapshot)
        restore_document_snapshot(collections, snapshot)
        atomic_json(folder / 'manifest.json', {'schema': 1, 'owner': 'usage', 'reverse_export': True, **verification})
        atomic_json(root / 'store.json', {'schema': 1, 'adapter': 'document',
            'retire_to': str(folder.relative_to(root) / 'retired.sqlite')})
        _retire_after_rollback(root)
        return {'status': 'rolled_back', 'backup': str(folder.relative_to(repository_root)),
            'restart_required': True, 'required_environment': {'MAVERICK_USAGE_STORE': 'document'}, **verification}


def _retire_after_rollback(root: Path) -> None:
    try:
        marker = json.loads((root / 'store.json').read_text())
    except FileNotFoundError:
        return
    destination = marker.get('retire_to')
    if not destination:
        return
    if not re.fullmatch(r'backups/[0-9a-f]{32}/retired.sqlite', destination):
        raise RuntimeError('Invalid Usage rollback retirement path.')
    source = root / 'usage.sqlite'
    if source.exists():
        with UsageSqliteStore(source).connection(write=True) as connection:
            connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            connection.execute('PRAGMA journal_mode=DELETE')
        os.replace(source, root / destination)
    atomic_json(root / 'store.json', {'schema': 1, 'adapter': 'document'})


def _backup_folder(root: Path) -> Path:
    folder = root / 'backups' / uuid4().hex
    folder.mkdir(parents=True)
    folder.chmod(0o2770)
    return folder
